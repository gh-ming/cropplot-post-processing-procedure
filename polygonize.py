import os
import cv2
import numpy as np
from osgeo import gdal, ogr, osr
from skimage import morphology
from skimage.morphology import square
import numpy as np
from scipy.ndimage import label, binary_erosion

def hysteresis_threshold(image, low_thresh=None, high_thresh=None):
    """
    Apply hysteresis thresholding to an image.

    Args:
        image (np.array): Input grayscale image of edge intensities.
        low_thresh (int or float): Low threshold.
        high_thresh (int or float): High threshold.

    Returns:
        np.array: The binary image with hysteresis thresholding applied.
    """
    if high_thresh is None:
        high_thresh = np.percentile(image[image > 0], 70) # 自动计算高阈值
    if low_thresh is None:
        low_thresh = high_thresh * 0.4 # 业内常用比例

    print(f"Hysteresis thresholds: low={low_thresh}, high={high_thresh}")

    # 找到强边界和弱边界
    strong_edges = (image >= high_thresh)
    weak_edges = (image >= low_thresh) & (image < high_thresh)

    # 使用连通组件分析找到连接到强边界的弱边界
    # 我们只关心那些与强边界“接触”的弱边界区域
    # structure 定义了8连通
    structure = np.ones((3, 3), dtype=np.int8)
    labeled_weak, num_labels = label(weak_edges, structure=structure)
    
    # 找到与强边界重叠的弱边界区域的label ID
    # binary_erosion 确保我们只在强边界像素本身上寻找，而不是其邻域
    import ipdb; ipdb.set_trace()
    strong_mask = binary_erosion(strong_edges, structure=structure)
    overlapping_labels = np.unique(labeled_weak[strong_mask])

    # 创建最终的二值图像
    binary_output = np.zeros_like(image, dtype=np.uint8)
    binary_output[strong_edges] = 255
    
    # 将连接到强边界的弱边界也加入结果
    for l in overlapping_labels:
        if l > 0: # 忽略背景label 0
            binary_output[labeled_weak == l] = 255
            
    return binary_output


def reclassify(img, window=31, threshold_a=2):
    return cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, window, threshold_a)

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

def extract_center_line(img):
    img = np.where(img>0, 0, 1)
    skeleton_img = morphology.skeletonize(img)
    return skeleton_img

def line_img_clean(img, small_objects_size=100):
    labels = morphology.label(img,1, connectivity=1)
    dst1 = morphology.opening(labels)
    dst2 = morphology.closing(dst1)
    dst3 = morphology.remove_small_objects(dst2, small_objects_size)
    dst1 = morphology.opening(dst3, square(5))
    dst2 = morphology.closing(dst1, square(5))
    # dst3 = morphology.remove_small_holes(dst2, 200, connectivity=2)
    dst2[dst2 == 0 ] = 1
    # boundary = find_boundaries(dst3, mode='outer').astype(np.uint8)

    return dst2

def raster_to_polygon_smooth(raster_filename, shapefile_filename):
    image = gdal.Open(raster_filename).ReadAsArray()
    # image = 255 - image

    # reclass = hysteresis_threshold(image, low_thresh=60, high_thresh=150)
    reclass = reclassify(image)
    open_reclass = morphology.opening(reclass, square(5))
    closed_reclass = morphology.closing(open_reclass, square(5))
    closed_reclass = closed_reclass.astype(np.uint16)

    line = extract_center_line(reclass)
    line = line.astype(np.uint16)
    clean_line = line_img_clean(line)
    clean_line = clean_line.astype(np.uint16)
    # cv2.imwrite(r'F:\CSCT-HD\test\parcel\clean_line.png', clean_line)

    output_raster = r'F:\CSCT-HD\test\parcel\clean_line_10202.tif'
    driver = gdal.GetDriverByName('GTiff')  
    out_raster = driver.Create(output_raster, image.shape[1], image.shape[0], 1, gdal.GDT_UInt32)
    out_raster.SetGeoTransform(gdal.Open(raster_filename).GetGeoTransform())
    out_raster.SetProjection(gdal.Open(raster_filename).GetProjection())
    out_raster.GetRasterBand(1).WriteArray(clean_line)
    out_raster.FlushCache()
    line2shp(output_raster, shapefile_filename, pred_band=1)


in_raster = r"F:\CSCT-HD\test\edge\GF_NM_T48TXL_E67973_N450835.tif"
out_shp = r"F:\CSCT-HD\test\parcel\test2_txy.shp"
raster_to_polygon_smooth(in_raster, out_shp)
