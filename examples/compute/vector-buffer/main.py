import geopandas as gpd

def run(context):
    frame=gpd.read_file(context.input_path('features'),layer='data')
    geographic=frame.to_crs(4326)
    bounds=geographic.total_bounds
    if bounds[2]-bounds[0]>6 or bounds[3]-bounds[1]>8:
        raise ValueError('数据跨度过大，请先裁剪到区域')
    projected=frame.to_crs(frame.estimate_utm_crs())
    projected.geometry=projected.geometry.buffer(context.parameters['distance'])
    projected.to_crs(frame.crs).to_file(context.output_path('buffer.gpkg'),layer='buffer',driver='GPKG')
