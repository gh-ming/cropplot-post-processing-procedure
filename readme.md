
From Edge Probability Map to Vector Parcels：an effective cropplot post-processing procedure

$$Huaming Gao$$

$$State Key Laboratory of Remote Sensing and Digital Earth$$

$$2025.10.21$$

1. 概述 (Overview)
   
本项目旨在提供一个完整的、从深度学习模型输出的边缘概率图 (Edge Probability Map) 到最终生产级矢量地块 (Production-Ready Vector Parcels) 的全自动化后处理管线。

在农田遥感监测领域，深度学习模型（如基于CNN、Transformer的模型）能有效识别地块边界，但其直接输出的栅格结果往往存在噪声、断裂、宽度不一、拓扑错误（如悬挂线）等问题，无法直接应用于下游的GIS分析和农业管理。本管线通过一系列创新性的、高度优化的图像处理、拓扑分析和几何计算，系统性地解决了这些挑战，将粗糙的栅格预测转化为干净、拓扑正确、几何精确且属性丰富的矢量数据。

2. 核心特性与贡献 (Key Features & Contributions)
   
本管线凝结了一系列探索与创新，其核心贡献在于开发了一套鲁棒、高效且科学的后处理算法，以应对真实世界遥感数据的复杂性：

    ✨ 基于几何形态的边界中心线提取:

    摒弃了在充满噪声的原始强度图上直接操作的传统思路。我们创新性地利用距离变换 (Distance Transform) 将边界区域转化为具有清晰几何结构的“山脊”地形图，再结合Hessian矩阵分析 (Meijering 滤波器) 精确提取“山脊线”，从原理上保证了中心线的平滑、合理性与鲁棒性。

    🧠 高速拓扑感知的骨架剪枝算法:
    针对骨架化过程中产生的“悬挂线”伪影（包括多级悬挂），开发了一套最终版的剪枝算法 (prune_dangling_lines_fast)。该算法基于标准的交叉数 (Crossing Number) 定义精确识别拓扑末端点，并通过查找表(LUT)与卷积相结合的方式实现了完全向量化，处理大尺寸影像时性能极高，能彻底、高效地清除所有层级的悬挂线。

    📐 几何保真的可变宽度重建:

    采用一套**拓扑清理 + 基于距离变换的几何重建**解决方案 (reconstruct_variable_width_from_skeleton)。在通过剪枝获得拓扑干净的单像素骨架后，利用距离变换的索引功能，并行地为骨架上的每个点匹配其在原始边界掩码中的真实“半径”，从而在恢复边界宽度的同时，完美保留了原始边界的多样性和不均匀性，解决了传统固定宽度膨胀导致的信息损失问题。

    🌍 投影感知的矢量处理:

    在矢量平滑与简化阶段，严格遵循GIS最佳实践。所有依赖于距离的计算（如滑动窗口平滑、Douglas-Peucker简化）都在投影坐标系 (UTM) 下进行，确保了相关参数（如tolerance）具有明确的米制单位，避免了在WGS84等地理坐标系下直接操作导致的变形和不一致性，保证了处理结果的地理精度。

    🧩 模块化的完整处理链:

    将整个复杂流程拆分为栅格预处理 (thinning.py)、矢量化 (thinning.py)、矢量后处理 (smooth.py)、语义过滤 (filter_by_cropland.py) 等多个独立、可配置的Python脚本，提高了代码的可维护性、可重用性和流程的灵活性。用户可根据需要选择性地执行或调整各个阶段。

3. 处理管线详解 (The Processing Pipeline)
   
    整个工作流从一个输入的边缘概率图GeoTIFF开始，到最终输出一个干净的农田地块Shapefile结束，共分为四个主要阶段：

    阶段一：栅格边界精炼与拓扑清理

    脚本: thinning.py
    输入: 原始边缘概率图GeoTIFF (假设边界为暗值)。

    核心步骤:

    - 构建距离图: 反转概率图 -> 定义“地块内部” -> 形态学清理 -> 距离变换 (distance_transform_edt)。
    提取中心线: 对距离图应用 Hessian (Meijering) 滤波器 -> Otsu自动阈值。

    - 处理边缘效应: 添加外围边界框架 (add_thick_border_frame)。

    - 预处理与骨架化: (可选) 提取最大连通域 -> skeletonize。

    - 拓扑剪枝: 应用高速向量化剪枝 (prune_dangling_lines_fast)。

    - 几何重建: 应用可变宽度重建 (reconstruct_variable_width_from_skeleton)。

    - 实例分割与过滤: label + remove_small_objects。

    - 输出: 临时的、带地理信息的、已清理的栅格实例图 (GeoTIFF)。

    阶段二：矢量化 (Vectorization)

    脚本: thinning.py (内部调用line2shp函数)

    输入: 阶段一输出的栅格实例图。

    核心步骤: 调用 gdal.Polygonize() 将栅格转换为矢量。

    输出: 原始的、带有锯齿边界的矢量地块文件 (Shapefile)。

    阶段三：矢量后处理 (Vector Post-Processing)

    脚本: smooth.py

    输入: 阶段二输出的原始矢量文件 (WGS84)。

    核心步骤:

    - 边界平滑: 应用基于滑动窗口的方向保持平滑 (smooth_parcels_by_window)。
  
    - 顶点简化: 
        投影: WGS84 -> UTM (_reproject_layer)。
        简化: 在UTM下应用Douglas-Peucker (geom.Simplify)，容差以米为单位。
        反向投影: UTM -> WGS84 (_reproject_layer)。
    - 输出: 边界平滑、顶点数量合理的优化矢量文件 (Shapefile, WGS84)。
  
    阶段四：语义过滤 (Semantic Filtering)

    脚本: filter_by_cropland.py

    输入: 阶段三输出的优化矢量文件和耕地范围栅格掩膜 (Mask TIF)。

    核心步骤: 计算每个地块与耕地掩膜的重叠率 (filter_parcels_by_mask_gdal)，并根据阈值进行过滤。

    输出: 最终的、高质量的农田地块矢量成果 (Shapefile)。
    
4. 如何使用 (How to Use)
4.1 环境配置
强烈建议使用Conda创建一个独立的Python环境，并从conda-forge渠道安装所有依赖，以确保库之间的兼容性。
# 创建新环境 (Python 3.8或更高版本)
conda create -n geo_env python=3.9

# 激活环境
conda activate geo_env

# 从 conda-forge 安装所有必需的库
conda install -c conda-forge gdal scikit-image scipy matplotlib opencv numpy pandas




4.2 依赖库
numpy
gdal (osgeo)
opencv-python (cv2)
scikit-image (skimage)
scipy
matplotlib (用于可视化)
pandas (用于skan, 如果使用skan剪枝)
4.3 运行流程
按顺序执行以下Python脚本，并根据您的文件路径和参数需求修改每个脚本末尾的 if __name__ == '__main__': 部分。
thinning.py:
配置: 设置输入边缘概率图 (in_raster) 和阶段二输出的原始矢量路径 (shapefile_filename)。根据需要调整内部参数（如定义内部区域的阈值、Hessian滤波器的sigmas等）。
运行: python thinning.py
smooth.py:
配置: 设置输入Shapefile (input_shp，指向上一步的输出)，最终简化后的输出Shapefile (output_shp_simple)，以及中间平滑结果的路径 (output_shp)。
重要: 设置正确的 TARGET_UTM_EPSG_CODE。
调整: window_size, strength (平滑参数)，tolerance_in_meters (简化参数)。
运行: python smooth.py
filter_by_cropland.py:
配置: 设置输入Shapefile (parcel_shp，指向上一步的输出)，耕地掩膜文件 (mask_tif)，以及最终过滤结果的输出路径 (output_shp)。
调整: threshold (重叠率阈值，0到1之间)。
运行: python filter_by_cropland.py
5. 引用 (Citation)
如果本项目对您的研究有所帮助，请考虑引用以下关键技术或库：
核心算法思想: Gao, H. (2025). 农田地块智能提取与精处理管线 [Algorithm Documentation]. State Key Laboratory of Remote Sensing and Digital Earth, Aerospace Information Research Institute, Chinese Academy of Sciences.
GDAL/OGR: GDAL/OGR Contributors. (2023). GDAL/OGR Geospatial Data Abstraction software Library. Open Source Geospatial Foundation. https://gdal.org
Scikit-image: Van der Walt, S., Schönberger, J. L., Nunez-Iglesias, J., Boulogne, F., Warner, J. D., Yager, N., ... & Yu, T. (2014). scikit-image: image processing in Python. PeerJ, 2, e453.
SciPy: Virtanen, P., Gommers, R., Oliphant, T. E., Haberland, M., Reddy, T., Cournapeau, D., ... & SciPy 1.0 Contributors. (2020). SciPy 1.0: fundamental algorithms for scientific computing in Python. Nature methods, 17(3), 261-272.
OpenCV: Bradski, G. (2000). The OpenCV Library. Dr. Dobb's Journal of Software Tools.
NumPy: Harris, C. R., Millman, K. J., van der Walt, S. J., Gommers, R., Virtanen, P., Cournapeau, D., ... & Oliphant, T. E. (2020). Array programming with NumPy. Nature, 585(7825), 357-362.
启发性工作: 本工作流的部分后处理思想（如多层次处理边界强度）受到了以下研究的启发：
Wu, W., Chen, T., Yang, H., He, Z., Chen, Y., & Wu, N. (2023). Multilevel segmentation algorithm for agricultural parcel extraction from a semantic boundary. International Journal of Remote Sensing, 44(3), 1045-1068. DOI: 10.1080/01431161.2023.2174386
6. 未来工作 (Future Work)
并行化处理: 将分块处理（Tiling）策略与multiprocessing库结合，以在多核CPU上并行处理大范围影像。
参数自动化: 探索基于图像特征自动确定平滑、简化和过滤参数最优值的方法。
拓扑修复: 在矢量化后，增加更高级的拓扑检查与修复步骤（如使用GEOS修复微小的几何错误）。
用户界面: 开发一个简单的图形用户界面（GUI），方便非编程人员使用。
