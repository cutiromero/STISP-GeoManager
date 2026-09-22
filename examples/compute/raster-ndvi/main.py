import numpy as np
import rasterio

def run(context):
    red_band=context.parameters['red']
    nir_band=context.parameters['nir']
    if red_band==nir_band:
        raise ValueError('红光与近红外波段不能相同')
    with rasterio.open(context.input_path('image')) as src:
        profile=src.profile.copy()
        profile.update(driver='GTiff',count=1,dtype='float32',nodata=-9999.0,compress='deflate')
        with rasterio.open(context.output_path('ndvi.tif'),'w',**profile) as dst:
            for _,window in src.block_windows(red_band):
                red=src.read(red_band,window=window,masked=True).astype('float32')*src.scales[red_band-1]+src.offsets[red_band-1]
                nir=src.read(nir_band,window=window,masked=True).astype('float32')*src.scales[nir_band-1]+src.offsets[nir_band-1]
                with np.errstate(divide='ignore',invalid='ignore'):
                    values=(nir-red)/(nir+red)
                values=np.ma.masked_where((nir+red)==0,np.ma.masked_invalid(values))
                dst.write(values.filled(-9999.0),1,window=window)
