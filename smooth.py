from osgeo import ogr, osr
import math
import os
from osgeo import ogr, osr
import math
import os

def smooth_polygon_by_window(geom, window_size=5, strength=0.3, corner_angle_threshold=160):
    """
    使用可变窗口对多边形边缘进行平滑，并增加了角点保护功能。
    ----------------------------------------------------------
    参数：
        geom: ogr.Geometry (Polygon)
        window_size: int, 邻域窗口大小（必须是>=3的奇数）。
        strength: float, 平滑程度(0~1)。
        corner_angle_threshold: float, 角点保护阈值（度）。小于此角度的顶点不进行平滑。
    返回：
        ogr.Geometry
    """
    assert window_size >= 3 and window_size % 2 != 0, "window_size 必须是 >= 3 的奇数"

    if geom.GetGeometryType() != ogr.wkbPolygon or geom.IsEmpty():
        return geom.Clone()

    ring = geom.GetGeometryRef(0)
    n_points = ring.GetPointCount()

    if n_points < window_size:
        return geom.Clone()

    coords = [ring.GetPoint(i) for i in range(n_points)]
    smoothed = []
    
    half_window = (window_size - 1) // 2

    for i in range(n_points):
        current = coords[i]
        
        # --- 新增：角点保护逻辑 ---
        # 角点角度始终由最近的3个点决定
        prev_for_angle = coords[(i - 1 + n_points) % n_points]
        next_for_angle = coords[(i + 1) % n_points]
        
        # 计算向量 v1 (current -> prev) 和 v2 (current -> next)
        v1 = (prev_for_angle[0] - current[0], prev_for_angle[1] - current[1])
        v2 = (next_for_angle[0] - current[0], next_for_angle[1] - current[1])

        mag_v1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag_v2 = math.sqrt(v2[0]**2 + v2[1]**2)

        is_corner = False
        if mag_v1 > 0 and mag_v2 > 0:
            dot_product = v1[0] * v2[0] + v1[1] * v2[1]
            cos_angle = max(-1.0, min(1.0, dot_product / (mag_v1 * mag_v2)))
            angle_deg = math.degrees(math.acos(cos_angle))
            
            if angle_deg < corner_angle_threshold:
                is_corner = True

        if is_corner:
            # 如果是角点，则不进行平滑，直接保留原坐标
            smoothed.append((current[0], current[1]))
            continue
        # --- 角点保护逻辑结束 ---

        # 如果不是角点，则执行基于 window_size 的平滑
        prev_point = coords[(i - half_window + n_points) % n_points]
        next_point = coords[(i + half_window) % n_points]

        dx = next_point[0] - prev_point[0]
        dy = next_point[1] - prev_point[1]
        norm = math.sqrt(dx**2 + dy**2)

        if norm == 0:
            smoothed.append((current[0], current[1]))
            continue

        ux, uy = dx / norm, dy / norm
        proj_len = (current[0] - prev_point[0]) * ux + (current[1] - prev_point[1]) * uy
        target_x = prev_point[0] + proj_len * ux
        target_y = prev_point[1] + proj_len * uy

        new_x = current[0] * (1 - strength) + target_x * strength
        new_y = current[1] * (1 - strength) + target_y * strength

        smoothed.append((new_x, new_y))

    new_ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in smoothed:
        new_ring.AddPoint(x, y)
    new_ring.CloseRings()

    new_poly = ogr.Geometry(ogr.wkbPolygon)
    new_poly.AddGeometry(new_ring)
    return new_poly



def simplify_and_smooth_parcels(
    input_shp: str, 
    output_shp: str, 
    target_utm_epsg: int, 
    simplify_tolerance: float,
    smooth_window_size: int = 5,
    smooth_strength: float = 0.5,
    corner_angle_threshold: float = 160
):
    """
    【最终版】通过“先简化，再平滑”的两阶段流程，完美处理锯齿问题。
    流程: WGS84 -> UTM -> Simplify(DP) -> Smooth(Window) -> WGS84
    """
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(output_shp):
        driver.DeleteDataSource(output_shp)

    in_ds = ogr.Open(input_shp)
    if in_ds is None:
        raise IOError(f"错误：无法打开输入文件 {input_shp}")
    in_lyr = in_ds.GetLayer()
    
    feature_count = in_lyr.GetFeatureCount()
    if feature_count == 0: return

    source_srs = in_lyr.GetSpatialRef()
    target_srs_utm = osr.SpatialReference()
    target_srs_utm.ImportFromEPSG(target_utm_epsg)
    
    wgs84_to_utm = osr.CoordinateTransformation(source_srs, target_srs_utm)
    utm_to_wgs84 = osr.CoordinateTransformation(target_srs_utm, source_srs)

    out_ds = driver.CreateDataSource(output_shp)
    out_lyr = out_ds.CreateLayer("final_smooth", source_srs, in_lyr.GetGeomType())
    out_lyr.CreateFields(in_lyr.schema)

    print(f"开始对 {feature_count} 个地块进行两阶段处理 (简化+平滑)...")
    
    in_lyr.ResetReading()
    for i, feat in enumerate(in_lyr):
        geom_wgs84 = feat.GetGeometryRef()
        if geom_wgs84 is None or geom_wgs84.IsEmpty(): continue

        # --- 核心处理流程 ---
        # 1. 投影到 UTM
        geom_utm = geom_wgs84.Clone()
        geom_utm.Transform(wgs84_to_utm)
        
        # 2. 【第一阶段】在UTM下进行DP简化，消除高频锯齿
        simplified_utm_geom = geom_utm.Simplify(simplify_tolerance)
        
        if simplified_utm_geom is None or simplified_utm_geom.IsEmpty(): continue
        
        # 3. 【第二阶段】对简化后的结果进行滑动窗口平滑，美化外观
        final_utm_geom = smooth_polygon_by_window(
            simplified_utm_geom, 
            smooth_window_size, 
            smooth_strength,
            corner_angle_threshold
        )
        
        # 4. 投影回WGS84
        final_wgs84_geom = final_utm_geom
        final_wgs84_geom.Transform(utm_to_wgs84)
        
        # --------------------
        
        out_feat = ogr.Feature(out_lyr.GetLayerDefn())
        out_feat.SetGeometry(final_wgs84_geom)
        for j in range(feat.GetFieldCount()):
            out_feat.SetField(j, feat.GetField(j))
        out_lyr.CreateFeature(out_feat)
        out_feat = None
        
        if (i + 1) % 1000 == 0 or (i + 1) == feature_count:
            print(f"  ...已处理 {i + 1} / {feature_count}")

    in_ds, out_ds = None, None
    print(f"✅ 两阶段处理完成 → {output_shp}")
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Parcel Simplify and Smooth Script')
    parser.add_argument('--input_shp', type=str, required=True, help='输入地块矢量文件（Shapefile）')
    parser.add_argument('--output_shp', type=str, required=True, help='输出平滑后的地块矢量文件（Shapefile）')
    parser.add_argument('--target_utm_epsg', type=int, default=32650, help='目标UTM投影的EPSG代码（例如：32650）')
    parser.add_argument('--simplify_tolerance', type=float, default=2.0, help='简化容差（米），用于消除锯齿')
    parser.add_argument('--smooth_window_size', type=int, default=3, help='平滑窗口大小（奇数>=3）')
    parser.add_argument('--smooth_strength', type=float, default=0.5, help='平滑强度(0~1)')
    parser.add_argument('--corner_angle_threshold', type=float, default=160.0, help='角点保护阈值（度）')
    args = parser.parse_args()
    simplify_and_smooth_parcels(
        input_shp=args.input_shp,
        output_shp=args.output_shp,
        target_utm_epsg=args.target_utm_epsg,
        simplify_tolerance=args.simplify_tolerance,  # 2米容差，用于消除像素级锯齿，根据分辨率调整，容差越大越平滑
        smooth_window_size=args.smooth_window_size,    # 3点窗口平滑,窗口越大平滑效果越明显但也会导致边界偏移丢失细节
        smooth_strength=args.smooth_strength,      # 0.5强度平滑
        corner_angle_threshold=args.corner_angle_threshold # 角点保护阈值，单位：度
    )




