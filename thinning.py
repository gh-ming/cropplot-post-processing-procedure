import numpy as np
from osgeo import gdal, ogr, osr
import cv2
from skimage import morphology
from skimage.filters import meijering
from scipy.signal import convolve2d
from scipy.ndimage import distance_transform_edt
from scipy.ndimage import label

def add_thick_border_frame(skeleton_map: np.ndarray, width: int = 2) -> np.ndarray:
    """
    为一个二值边界图直接增加一个固定宽度的外边界框架。

    这是一个简单而强大的方法，用于强制闭合所有在图像边缘被切断的多边形。

    Args:
        skeleton_map (np.ndarray): 输入的单像素宽或多像素宽的二值边界图。
        width (int): 要绘制的边界框架的像素宽度。默认为2。

    Returns:
        一个增加了厚实外边界的二值边界图。
    """
    # 创建一个副本以避免修改原始图像
    bordered_map = skeleton_map.copy()
    rows, cols = bordered_map.shape

    # --- 绘制两像素宽的边界 ---
    # 顶部
    bordered_map[0:width, :] = 1
    # 底部
    bordered_map[rows-width:rows, :] = 1
    # 左侧
    bordered_map[:, 0:width] = 1
    # 右侧
    bordered_map[:, cols-width:cols] = 1
    
    return bordered_map


# _get_crossing_number 函数保持不变，用于创建查找表
def _get_crossing_number(neighborhood: np.ndarray) -> int:
    neighbors = [
        neighborhood[0, 1], neighborhood[0, 2], neighborhood[1, 2], neighborhood[2, 2],
        neighborhood[2, 1], neighborhood[2, 0], neighborhood[1, 0], neighborhood[0, 0]
    ]
    neighbors_circular = neighbors + [neighbors[0]]
    crossings = 0
    for i in range(len(neighbors)):
        if neighbors_circular[i] == 0 and neighbors_circular[i+1] == 1:
            crossings += 1
    return crossings

def _create_crossing_number_lut() -> np.ndarray:
    """预先计算所有256种邻域模式的交叉数，生成查找表。"""
    lut = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        # 将整数i转换为8位的二进制，模拟一个3x3邻域
        binary = format(i, '08b')
        neighbors = np.array([int(b) for b in binary])
        
        # 构建3x3邻域矩阵
        neighborhood = np.zeros((3, 3), dtype=np.uint8)
        neighborhood[0, 1] = neighbors[0]
        neighborhood[0, 2] = neighbors[1]
        neighborhood[1, 2] = neighbors[2]
        neighborhood[2, 2] = neighbors[3]
        neighborhood[2, 1] = neighbors[4]
        neighborhood[2, 0] = neighbors[5]
        neighborhood[1, 0] = neighbors[6]
        neighborhood[0, 0] = neighbors[7]
        
        lut[i] = _get_crossing_number(neighborhood)
    return lut

def prune_dangling_lines_fast(skeleton_map: np.ndarray) -> np.ndarray:
    """
    剪枝算法的高速向量化版本。

    Args:
        skeleton_map (np.ndarray): 输入的单像素宽二值边界图。

    Returns:
        一个清除了所有悬挂线的二值边界图。
    """
    pruned_map = skeleton_map.copy()
    
    # 1. 创建查找表 (只需一次)
    crossing_number_lut = _create_crossing_number_lut()
    
    # 2. 定义卷积核，用于并行计算每个像素的邻域编码
    #    每个邻居对应一个2的幂
    #    128 64 32
    #    1   X  16
    #    2   4  8
    kernel = np.array([
        [128, 64, 32],
        [1,   0,  16],
        [2,   4,  8]
    ], dtype=np.uint8)

    while True:
        # 3. 使用卷积计算邻域编码图
        #    这一步取代了内层的双重for循环
        neighborhood_codes = convolve2d(pruned_map, kernel, mode='same')
        
        # 4. 应用查找表，得到交叉数图
        crossing_number_map = crossing_number_lut[neighborhood_codes]
        
        # 5. 找到所有末端点
        #    条件：是骨架上的点，且交叉数为1
        endpoints_mask = (pruned_map == 1) & (crossing_number_map == 1)

        # 如果没有找到任何末端点，则清理完成
        if not np.any(endpoints_mask):
            break
        
        # 6. 一次性移除所有找到的末端点
        pruned_map[endpoints_mask] = 0
            
    return pruned_map

def reconstruct_variable_width_from_skeleton(
    pruned_skeleton: np.ndarray, 
    original_thick_mask: np.ndarray
) -> np.ndarray:
    """
    最终解决方案：基于干净的骨架和距离变换，精确重建可变宽度的边界。

    Args:
        pruned_skeleton (np.ndarray): 拓扑干净的单像素骨架（种子）。
        original_thick_mask (np.ndarray): 原始的、有缺陷但宽度正确的边界掩码。

    Returns:
        一个拓扑干净且几何形状被精确恢复的最终边界掩码。
    """

    # 步骤1: 几何分析，获取原始宽度信息 (不变)
    width_map = distance_transform_edt(original_thick_mask > 0)

    # 步骤2: 创建“种子宽度图”，只在干净骨架位置有宽度值
    seed_width_map = width_map * (pruned_skeleton > 0)
    
    # 步骤3: 执行距离变换，同时获取到最近种子点的距离和索引
    # 对“非种子点”进行变换
    dists, indices = distance_transform_edt(
        seed_width_map == 0,
        return_distances=True,
        return_indices=True
    )
    
    # 步骤4: 利用索引图，从种子宽度图中重建出完整的半径图
    # indices[0] 是行坐标, indices[1] 是列坐标
    # 这步是关键，它为每个像素找到了其对应的种子点的宽度值
    reconstructed_radii = seed_width_map[indices[0], indices[1]]
    
    # 步骤5: 最终比较：一个点是否属于最终边界，取决于它到种子的距离是否小于等于该种子的半径
    final_mask = (dists <= reconstructed_radii).astype(np.uint8)

    return final_mask
def line2shp(raster_filename, shapefile_filename, pred_band=1):
    raster_dataset = gdal.Open(raster_filename)
    if raster_dataset is None:
        print('[FATAL] GDAL open file failed. [%s]' % raster_filename)
        exit(1)

    driver = ogr.GetDriverByName('ESRI Shapefile')
    if driver is None:
        print('[FATAL] OGR create driver failed. [%s]' % 'ESRI Shapefile')
        exit(1)

    shape_dataset = driver.CreateDataSource(shapefile_filename)
    if shape_dataset is None:
        print('[FATAL] OGR create file failed. [%s]' % shapefile_filename)
        exit(1)

    proj_ref = raster_dataset.GetProjectionRef()
    proj_shp = osr.SpatialReference()
    proj_shp.ImportFromWkt(proj_ref)
    layer = shape_dataset.CreateLayer('pred', proj_shp, ogr.wkbPolygon)
    field_name = ogr.FieldDefn('objects', ogr.OFTInteger)
    layer.CreateField(field_name)
    band = raster_dataset.GetRasterBand(pred_band)
    gdal.Polygonize(band, band, layer, 0)
    del shape_dataset


if __name__ == '__main__':
    in_raster = r"F:\CSCT-HD\test\edge\GF_NM_T48TXL_E67973_N450835.tif"
    output_raster = r'F:\CSCT-HD\test\parcel\test4.tif'
    shapefile_filename = r'F:\CSCT-HD\test\parcel\test4.shp'

    # 1. 读取边界强度图，并计算内部区域掩码
    image = gdal.Open(in_raster).ReadAsArray()
    edge_intensity_map = 255 - image # 输入的是“反转”的边缘图，即边界为暗(值低)，地块为亮(值高)

    # 获取内部区域掩码（边界强度低于50的区域为内部）
    interiors_mask = np.where(edge_intensity_map < 50,1,0)
    dst1 = morphology.opening(interiors_mask)
    dst2 = morphology.closing(dst1)
    # 获取距离变换图，目的是为了后续重建可变宽度边界
    distance_map = distance_transform_edt(1 - dst2)
    # 2. 提取脊线，并用otsu法二值化（参考arcgis的思想）
    ridgeness_map = meijering(distance_map, sigmas=(1,2), black_ridges=False)
    ridgeness_map_8bit = cv2.normalize(ridgeness_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    
    ridge_threshold_otsu, ridge_mask = cv2.threshold(
        ridgeness_map_8bit, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    skeleton_img = ridge_mask.astype(np.uint8)

    # 在骨架图四周增加1像素宽的边界，防止边缘效应
    pad = 1
    skeleton_img = np.pad(skeleton_img, pad_width=pad, mode='constant', constant_values=1)
    # 获取原始GeoTransform并调整
    src = gdal.Open(in_raster)
    gt = list(src.GetGeoTransform())
    pixel_w, pixel_h = gt[1], gt[5]
    gt[0] = gt[0] - pixel_w * pad        # 左移地理起点X
    gt[3] = gt[3] - pixel_h * pad        # 上移地理起点Y
    # skeleton_img = add_thick_border_frame(ridge_top_mask, width=1)

    # 3. 优化骨架，去除悬挂线和碎片
    instance_map_holey, num_instances = label(skeleton_img, structure=np.array([[0,1,0],[1,1,1],[0,1,0]]))
    instace_map = np.where(instance_map_holey==1,1,0) # 仅保留最大连通域
    skeleton = morphology.skeletonize(instace_map > 0)
    pruned = skeleton.copy().astype(np.uint8)
    # 进行剪枝，去除悬挂线（核心在于交叉点的定义）
    pruned = prune_dangling_lines_fast(pruned)
    # 重建可变宽度边界
    puned_last = reconstruct_variable_width_from_skeleton(pruned, skeleton_img)
    labels = morphology.label(puned_last,1, connectivity=1)
    result = morphology.remove_small_objects(labels, 100)


    # 4. 保存结果为栅格和矢量
    driver = gdal.GetDriverByName('GTiff')  
    out_raster = driver.Create(output_raster, skeleton_img.shape[1], skeleton_img.shape[0], 1, gdal.GDT_UInt32)
    out_raster.SetGeoTransform(gt)
    out_raster.SetProjection(src.GetProjection())
    out_raster.GetRasterBand(1).WriteArray(result)
    out_raster.FlushCache()
    line2shp(output_raster, shapefile_filename, pred_band=1)