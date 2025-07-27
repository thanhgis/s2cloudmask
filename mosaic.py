import os
import numpy as np
from osgeo import gdal
from pathlib import Path
import tempfile

class SimpleSentinel2Mosaic:
    def __init__(self, output_dir, temp_dir=None):
        self.output_dir = Path(output_dir)
        self.temp_dir = temp_dir or tempfile.mkdtemp()
        self.output_dir.mkdir(exist_ok=True)
        
        # All bands at 10m resolution
        self.bands_10m = ['B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12']
        
    def create_reference_grid(self, image_paths, pixel_size=10):
        """Create a reference grid from the first image to ensure consistency"""
        if not image_paths:
            raise ValueError("No input images provided")
            
        # Use first image as reference
        ref_ds = gdal.Open(image_paths[0])
        if ref_ds is None:
            raise ValueError(f"Cannot open reference image: {image_paths[0]}")
            
        # Get reference parameters
        ref_gt = ref_ds.GetGeoTransform()
        ref_proj = ref_ds.GetProjection()
        ref_width = ref_ds.RasterXSize
        ref_height = ref_ds.RasterYSize
        
        # Calculate reference extent
        ref_min_x = ref_gt[0]
        ref_max_y = ref_gt[3]
        ref_max_x = ref_gt[0] + ref_width * ref_gt[1]
        ref_min_y = ref_gt[3] + ref_height * ref_gt[5]
        
        ref_ds = None
        
        # Expand to include all images
        for path in image_paths[1:]:
            ds = gdal.Open(path)
            if ds is None:
                continue
                
            gt = ds.GetGeoTransform()
            width, height = ds.RasterXSize, ds.RasterYSize
            
            min_x = gt[0]
            max_y = gt[3]
            max_x = gt[0] + width * gt[1]
            min_y = gt[3] + height * gt[5]
            
            ref_min_x = min(ref_min_x, min_x)
            ref_max_x = max(ref_max_x, max_x)
            ref_min_y = min(ref_min_y, min_y)
            ref_max_y = max(ref_max_y, max_y)
            
            ds = None
        
        # Align to pixel grid
        ref_min_x = np.floor(ref_min_x / pixel_size) * pixel_size
        ref_max_x = np.ceil(ref_max_x / pixel_size) * pixel_size
        ref_min_y = np.floor(ref_min_y / pixel_size) * pixel_size
        ref_max_y = np.ceil(ref_max_y / pixel_size) * pixel_size
        
        # Calculate final dimensions
        width = int(np.round((ref_max_x - ref_min_x) / pixel_size))
        height = int(np.round((ref_max_y - ref_min_y) / pixel_size))
        
        # Create geotransform
        geotransform = (ref_min_x, pixel_size, 0, ref_max_y, 0, -pixel_size)
        
        return {
            'width': width,
            'height': height,
            'geotransform': geotransform,
            'projection': ref_proj,
            'bounds': [ref_min_x, ref_min_y, ref_max_x, ref_max_y]
        }
    
    def mosaic_band_median(self, image_paths, band_name, output_path, pixel_size = 10, nodata_value = 0):
        ref_info = self.create_reference_grid(image_paths, pixel_size)
        arrays = []
        for i, img_path in enumerate(image_paths):
            temp_path = os.path.join(self.temp_dir, f"temp_{i}_{band_name}.tif")
            warp_options = gdal.WarpOptions(
                format='GTiff',
                outputBounds=ref_info['bounds'],
                width=ref_info['width'],
                height=ref_info['height'],
                dstSRS=ref_info['projection'],
                srcNodata=nodata_value,
                dstNodata=nodata_value,
                resampleAlg='bilinear',
                creationOptions=['COMPRESS=LZW']
            )
            
            try:
                gdal.Warp(temp_path, img_path, options=warp_options)
                ds = gdal.Open(temp_path)
                if ds is not None:
                    array = ds.ReadAsArray()
                    if array is not None and array.shape == (ref_info['height'], ref_info['width']):
                        masked_array = np.ma.masked_equal(array, nodata_value)
                        arrays.append(masked_array)
                    else:
                        print(f"  Skipped: Invalid array shape")
                    ds = None
                else:
                    print(f"  Skipped: Could not open warped file")
                    
            except Exception as e:
                print(f"  Error warping {img_path}: {e}")
            
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
        if not arrays:
            raise ValueError("No valid arrays found for mosaicking")
               
        # Stack and compute median
        stacked = np.ma.stack(arrays, axis=0)
        median_result = np.ma.median(stacked, axis=0)
        
        # Fill masked values with nodata
        final_result = median_result.filled(nodata_value)
        
        # Create output dataset
        driver = gdal.GetDriverByName('GTiff')
        out_ds = driver.Create(
            output_path, 
            ref_info['width'], 
            ref_info['height'], 
            1, 
            gdal.GDT_UInt16,
            options=['COMPRESS=LZW', 'TILED=YES']
        )
        
        out_ds.SetGeoTransform(ref_info['geotransform'])
        out_ds.SetProjection(ref_info['projection'])
        out_ds.GetRasterBand(1).WriteArray(final_result)
        out_ds.GetRasterBand(1).SetNoDataValue(nodata_value)       
        out_ds = None
    
    def process_all_bands(self, scene_directories, output_name="mosaic"):
        bands_by_name = {}
        # Collect files by band
        for scene_dir in scene_directories:
            scene_path = Path(scene_dir)
            for band in self.bands_10m:
                pattern = f"*{band}*masked*.tif"
                matches = list(scene_path.glob(pattern))
                if matches:
                    if band not in bands_by_name:
                        bands_by_name[band] = []
                    bands_by_name[band].append(str(matches[0]))
        
        # Process each band
        mosaic_files = {}
        
        for band_name, file_paths in bands_by_name.items():
            if len(file_paths) >= 2:  # Need at least 2 files for mosaic
                output_path = self.output_dir / f"{output_name}_{band_name}_median.tif"
                try:
                    self.mosaic_band_median(file_paths, band_name, str(output_path))
                    mosaic_files[band_name] = str(output_path)
                except Exception as e:
                    print(f"Error processing band {band_name}: {e}")
            else:
                print(f"Skipping band {band_name}: insufficient files ({len(file_paths)})")
        
        # Create multi-band composite
        if mosaic_files:
            self.create_composite(mosaic_files, output_name)
        
        return mosaic_files
    
    def create_composite(self, band_files, output_name):
        """Create multi-band composite"""
        if not band_files:
            return
            
        output_path = self.output_dir / f"{output_name}_composite.tif"
        
        # Sort bands for consistent ordering
        sorted_bands = sorted(band_files.items())
        file_paths = [path for _, path in sorted_bands]
        
        # Create VRT
        vrt_path = str(output_path).replace('.tif', '_temp.vrt')
        vrt_options = gdal.BuildVRTOptions(separate=True)
        vrt_ds = gdal.BuildVRT(vrt_path, file_paths, options=vrt_options)
        vrt_ds = None
        
        # Convert to GeoTIFF
        translate_options = gdal.TranslateOptions(
            format='GTiff',
            creationOptions=['COMPRESS=LZW', 'TILED=YES']
        )
        
        gdal.Translate(str(output_path), vrt_path, options=translate_options)
        
        # Clean up
        if os.path.exists(vrt_path):
            os.remove(vrt_path)

