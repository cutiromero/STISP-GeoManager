import numpy as np
import rasterio

def run(context):
    with rasterio.open(context.input_path('source')) as src:
        profile=src.profile.copy()
        profile.update(driver='GTiff',dtype='float32',count=1,nodata=-9999.0,compress='deflate')
        with rasterio.open(context.output_path('transformed.tif'),'w',**profile) as dst:
            for _,window in src.block_windows(context.parameters['band']):
                values=src.read(context.parameters['band'],window=window,masked=True).astype('float32')
                result=values*context.parameters['scale']+context.parameters['offset']
                result=np.ma.masked_invalid(result)
                dst.write(result.filled(-9999.0),1,window=window)
