from osgeo import ogr, osr
import math
import os

def smooth_polygon_by_window(geom, window_size=5, strength=0.3):
    """
    使用可变窗口 (window_size) 对多边形边缘进行平滑。

    此版本不包含角点保护和空洞处理，专注于核心的平滑算法。
    ----------------------------------------------------------
    参数：
        geom: ogr.Geometry (Polygon)
        window_size: int, 邻域窗口大小（必须是>=3的奇数）。
        strength: float, 平滑程度(0~1)。
    返回：
        ogr.Geometry
    """
    # 确保 window_size 是一个大于等于3的奇数
    assert window_size >= 3 and window_size % 2 != 0, "window_size 必须是 >= 3 的奇数"

    if geom.GetGeometryType() != ogr.wkbPolygon or geom.IsEmpty():
        return geom.Clone()

    ring = geom.GetGeometryRef(0)
    n_points = ring.GetPointCount()

    # 如果点数过少，无法应用窗口，直接返回原始几何
    if n_points < window_size:
        return geom.Clone()

    coords = [ring.GetPoint(i) for i in range(n_points)]
    smoothed = []
    
    half_window = (window_size - 1) // 2

    for i in range(n_points):
        current = coords[i]
        
        # --- 基于 window_size 的平滑 ---
        prev_point = coords[(i - half_window + n_points) % n_points]
        next_point = coords[(i + half_window) % n_points]

        dx = next_point[0] - prev_point[0]
        dy = next_point[1] - prev_point[1]
        norm = math.sqrt(dx**2 + dy**2)

        if norm == 0:
            smoothed.append((current[0], current[1]))
            continue

        # 当前点到趋势线的投影
        ux, uy = dx / norm, dy / norm
        proj_len = (current[0] - prev_point[0]) * ux + (current[1] - prev_point[1]) * uy
        target_x = prev_point[0] + proj_len * ux
        target_y = prev_point[1] + proj_len * uy

        # 沿方向微调
        new_x = current[0] * (1 - strength) + target_x * strength
        new_y = current[1] * (1 - strength) + target_y * strength

        smoothed.append((new_x, new_y))

    # 重建多边形
    new_ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in smoothed:
        new_ring.AddPoint(x, y)
    new_ring.CloseRings()

    new_poly = ogr.Geometry(ogr.wkbPolygon)
    new_poly.AddGeometry(new_ring)
    return new_poly


def smooth_parcels_by_window(input_shp, output_shp, window_size=5, strength=0.5):
    """
    对输入地块 Shapefile 进行平滑处理。
    """
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(output_shp):
        driver.DeleteDataSource(output_shp)
    in_ds = ogr.Open(input_shp)
    in_lyr = in_ds.GetLayer()
    srs = in_lyr.GetSpatialRef()
    out_ds = driver.CreateDataSource(output_shp)
    out_lyr = out_ds.CreateLayer("smooth", srs, ogr.wkbPolygon)
    out_lyr.CreateFields(in_lyr.schema)

    in_lyr.ResetReading()
    for feat in in_lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        
        smooth_geom = smooth_polygon_by_window(geom, window_size, strength)
        
        out_feat = ogr.Feature(out_lyr.GetLayerDefn())
        out_feat.SetGeometry(smooth_geom)
        for i in range(feat.GetFieldCount()):
            out_feat.SetField(i, feat.GetField(i))
        out_lyr.CreateFeature(out_feat)
        out_feat = None

    in_ds, out_ds = None, None
    print(f"✅ 平滑完成 (窗口大小: {window_size}, 强度: {strength}) → {output_shp}")


def simplify_wgs84_parcels(
    input_wgs84_shp: str, 
    output_wgs84_shp: str, 
    target_utm_epsg: int, 
    tolerance_in_meters: float
):
    """
    【纯GDAL/OGR版】对WGS84坐标系的Shapefile进行精确简化，最终结果仍为WGS84。
    此版本不依赖Shapely，以避免底层库冲突导致的程序崩溃。
    流程: WGS84 -> UTM -> Simplify (in meters) -> WGS84

    参数:
        input_wgs84_shp (str): 输入的WGS84 Shapefile路径。
        output_wgs84_shp (str): 最终输出的WGS84 Shapefile路径。
        target_utm_epsg (int): 您数据所在区域对应的UTM Zone的EPSG代码。
        tolerance_in_meters (float): 简化容差，单位是米。
    """
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(output_wgs84_shp):
        driver.DeleteDataSource(output_wgs84_shp)

    # --- 1. 设置坐标系和转换关系 ---
    in_ds = ogr.Open(input_wgs84_shp)
    if in_ds is None:
        raise IOError(f"错误：无法打开输入文件 {input_wgs84_shp}")
    in_lyr = in_ds.GetLayer()
    
    feature_count = in_lyr.GetFeatureCount()
    if feature_count == 0:
        print("警告：输入文件为空，没有地块需要处理。")
        in_ds = None
        return

    # 源坐标系 (WGS84)
    source_srs = in_lyr.GetSpatialRef()
    # 目标坐标系 (UTM)
    target_srs_utm = osr.SpatialReference()
    target_srs_utm.ImportFromEPSG(target_utm_epsg)
    
    # 创建正向和反向的坐标转换对象
    wgs84_to_utm_transform = osr.CoordinateTransformation(source_srs, target_srs_utm)
    utm_to_wgs84_transform = osr.CoordinateTransformation(target_srs_utm, source_srs)

    # --- 2. 创建最终的输出文件 ---
    out_ds = driver.CreateDataSource(output_wgs84_shp)
    # 输出文件的坐标系是WGS84
    out_lyr = out_ds.CreateLayer("simplified_wgs84", source_srs, in_lyr.GetGeomType())
    out_lyr.CreateFields(in_lyr.schema)

    print(f"开始对 {feature_count} 个地块进行处理...")
    
    in_lyr.ResetReading()
    for i, feat in enumerate(in_lyr):
        try:
            geom_wgs84 = feat.GetGeometryRef()
            if geom_wgs84 is None or geom_wgs84.IsEmpty():
                continue

            # --- 核心处理流程 ---
            # a. 复制几何对象并投影到UTM
            geom_utm = geom_wgs84.Clone()
            geom_utm.Transform(wgs84_to_utm_transform)
            
            # b. 在UTM坐标系下，使用 OGR 内置的 Simplify 方法进行简化
            simplified_utm_geom = geom_utm.Simplify(tolerance_in_meters)
            
            # c. 如果简化后的几何为空，则跳过
            if simplified_utm_geom is None or simplified_utm_geom.IsEmpty():
                continue
                
            # d. 将简化后的几何投影回WGS84
            simplified_wgs84_geom = simplified_utm_geom
            simplified_wgs84_geom.Transform(utm_to_wgs84_transform)
            
            # --------------------
            
            out_feat = ogr.Feature(out_lyr.GetLayerDefn())
            out_feat.SetGeometry(simplified_wgs84_geom)
            for j in range(feat.GetFieldCount()):
                out_feat.SetField(j, feat.GetField(j))
            out_lyr.CreateFeature(out_feat)
            out_feat = None

        except Exception as e:
            feature_id = feat.GetFID()
            print(f"  [警告] 处理地块 FID: {feature_id} 时发生错误，已跳过。错误信息: {e}")
            continue

        # 打印进度
        if (i + 1) % 1000 == 0 or (i + 1) == feature_count:
            print(f"  ...已处理 {i + 1} / {feature_count}")

    in_ds, out_ds = None, None
    print(f"✅ 全部流程完成！最终文件已保存至 → {output_wgs84_shp}")



if __name__ == "__main__":
    TARGET_UTM_EPSG_CODE = 32650 # 示例：WGS 84 / UTM zone 50N
    output_shp_simple = r"F:\CSCT-HD\test\parcel\test3_smooth_simplified.shp"
    input_shp = r"F:\CSCT-HD\test\parcel\test3.shp"
    output_shp = r"F:\CSCT-HD\test\parcel\test3_smooth.shp"
    smooth_parcels_by_window(
        input_shp, 
        output_shp, 
        window_size=3,  # 使用3个点的窗口
        strength=0.5    # 平滑力度
    )
    simplify_wgs84_parcels(
        input_wgs84_shp=output_shp,
        output_wgs84_shp=output_shp_simple,
        target_utm_epsg=TARGET_UTM_EPSG_CODE,
        tolerance_in_meters=1  
    )





