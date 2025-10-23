from osgeo import ogr, gdal
import numpy as np
import os

def filter_parcels_by_mask_gdal(parcel_shp, mask_tif, threshold=0.5, output_shp=None):
    shp_ds = ogr.Open(parcel_shp)
    shp_lyr = shp_ds.GetLayer()
    mask_ds = gdal.Open(mask_tif)
    mask_band = mask_ds.GetRasterBand(1)
    gt = mask_ds.GetGeoTransform()
    nodata = mask_band.GetNoDataValue()

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if output_shp:
        if os.path.exists(output_shp):
            driver.DeleteDataSource(output_shp)
        out_ds = driver.CreateDataSource(output_shp)
    else:
        out_ds = driver.CreateDataSource("/vsimem/tmp.shp")

    out_lyr = out_ds.CreateLayer("filtered", shp_lyr.GetSpatialRef(), ogr.wkbPolygon)
    out_lyr.CreateFields(shp_lyr.schema)

    mem_driver = ogr.GetDriverByName("Memory")
    raster_driver = gdal.GetDriverByName("MEM")

    for feat in shp_lyr:
        geom = feat.GetGeometryRef()
        minx, maxx, miny, maxy = geom.GetEnvelope()
        px_min = int((minx - gt[0]) / gt[1])
        px_max = int((maxx - gt[0]) / gt[1])
        py_min = int((maxy - gt[3]) / gt[5])
        py_max = int((miny - gt[3]) / gt[5])
        if py_min > py_max: py_min, py_max = py_max, py_min

        px_min = max(0, px_min)
        py_min = max(0, py_min)
        px_max = min(mask_ds.RasterXSize, px_max)
        py_max = min(mask_ds.RasterYSize, py_max)

        win_xsize = px_max - px_min
        win_ysize = py_max - py_min
        if win_xsize <= 0 or win_ysize <= 0:
            continue

        mask_array = mask_band.ReadAsArray(px_min, py_min, win_xsize, win_ysize)
        if mask_array is None:
            continue

        mem_ds = raster_driver.Create("", win_xsize, win_ysize, 1, gdal.GDT_Byte)
        mem_ds.SetGeoTransform((gt[0] + px_min * gt[1], gt[1], 0.0,
                                gt[3] + py_min * gt[5], 0.0, gt[5]))
        mem_ds.SetProjection(mask_ds.GetProjection())

        # 临时图层仅含一个要素
        tmp_ds = mem_driver.CreateDataSource('wrk')
        tmp_lyr = tmp_ds.CreateLayer('single', shp_lyr.GetSpatialRef(), ogr.wkbPolygon)
        tmp_lyr.CreateFeature(feat.Clone())

        gdal.RasterizeLayer(mem_ds, [1], tmp_lyr, burn_values=[1])

        parcel_mask = mem_ds.ReadAsArray()
        valid = np.ones_like(mask_array, dtype=bool) if nodata is None else mask_array != nodata
        total = np.sum(parcel_mask[valid] == 1)
        overlap = np.sum((mask_array == 1) & (parcel_mask == 1))
        ratio = overlap / total if total > 0 else 0

        if ratio >= threshold:
            out_feat = ogr.Feature(out_lyr.GetLayerDefn())
            out_feat.SetGeometry(geom.Clone())
            for i in range(feat.GetFieldCount()):
                out_feat.SetField(i, feat.GetField(i))
            out_lyr.CreateFeature(out_feat)
            out_feat = None

        tmp_ds = None
        mem_ds = None

    print(f"✅ 过滤完成，输出地块数：{out_lyr.GetFeatureCount()}")
    shp_ds, mask_ds = None, None
    return out_ds
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Filter Parcels by Cropland Mask') 
    parser.add_argument('--parcel_shp', type=str, required=True, help='输入地块矢量文件（Shapefile）')
    parser.add_argument('--mask_tif', type=str, required=True, help='耕地掩膜文件（GeoTIFF）')
    parser.add_argument('--threshold', type=float, default=0.8, help='重叠比例阈值（0~1）')
    parser.add_argument('--output_shp', type=str, required=True, help='输出过滤后的地块矢量文件（Shapefile）')
    args = parser.parse_args()

    filter_parcels_by_mask_gdal(
        args.parcel_shp,    
        args.mask_tif,
        threshold=args.threshold,
        output_shp=args.output_shp
    )

