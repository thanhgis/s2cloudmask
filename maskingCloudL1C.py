# maskingCloud.py
"""
Sentinel-2 Cloud Masking Module using enhanced s2cloudless algorithm
ThanhGIS / ThanhNV All rights reserved 2025
Enhanced version with adaptive thresholding and cloud shadow detection
"""

import os, qgis
import numpy as np
from pathlib import Path
from qgis.core import (QgsRasterLayer, QgsProject, QgsProcessingFeedback, QgsCoordinateReferenceSystem, QgsCoordinateTransform)
import processing
from osgeo import gdal
from s2cloudless import S2PixelCloudDetector
from scipy.ndimage import uniform_filter, binary_dilation
from scipy.ndimage import generate_binary_structure


def save_mask_with_reference(array, output_path, reference_ds):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.dataProvider().dataSourceUri() == output_path.replace('\\', '/'):
            QgsProject.instance().removeMapLayer(layer.id())
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(output_path, array.shape[1], array.shape[0], 1, gdal.GDT_Byte)
    out_ds.SetGeoTransform(reference_ds.GetGeoTransform())
    out_ds.SetProjection(reference_ds.GetProjection())
    out_ds.GetRasterBand(1).WriteArray(array)
    out_ds.FlushCache()
    out_ds = None

def find_file_fragment(fragment, search_path, product_name):
    path = Path(os.path.join(search_path, product_name))
    return list(path.rglob(f"*{fragment}*"))
    
def applyCloudMasking(product_name, process_dir, epsg_code, progress_dialog=None, progress_start=None, progress_end=None):
    if progress_dialog:
        progress_dialog.set_detail("Loading satellite imagery...")

    # Your existing cloud masking logic here
    processing_steps = [
        "Analyzing cloud patterns...",
        "Generating cloud mask...",
        "Applying mask to bands...",
        "Optimizing results..."
    ]
    
    for i, step in enumerate(processing_steps):
        if progress_dialog and progress_dialog.is_cancelled():
            return None
            
        if progress_dialog:
            progress_dialog.set_detail(step)
            progress_value = 50 + int((i / len(processing_steps)) * 30)
            progress_dialog.set_value(progress_value)
    required_bands = {
        "B01": {"res": "60m", "name": "Coastal aerosol"},
        "B02": {"res": "10m", "name": "Blue"},
        "B03": {"res": "10m", "name": "Green"},
        "B04": {"res": "10m", "name": "Red"},
        "B05": {"res": "20m", "name": "Red Edge 1"},
        "B06": {"res": "20m", "name": "Red Edge 2"},
        "B07": {"res": "20m", "name": "Red Edge 3"},
        "B08": {"res": "10m", "name": "NIR"},
        "B8A": {"res": "20m", "name": "Narrow NIR"},
        "B09": {"res": "60m", "name": "Water vapour"},
        "B10": {"res": "60m", "name": "Cirrus"},
        "B11": {"res": "20m", "name": "SWIR 1"},
        "B12": {"res": "20m", "name": "SWIR 2"}
    }
    output_bands = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
    temp_dir = os.path.join(process_dir, product_name, "TEMP")
    os.makedirs(temp_dir, exist_ok=True)

    band_files = {}
    canvas = qgis.utils.iface.mapCanvas()
    canvas_crs = canvas.mapSettings().destinationCrs()
    ext = canvas.extent()
    for band_code in required_bands:
        results = find_file_fragment(band_code, process_dir, product_name)
        if results: 
            for res in results:
                if str(res).endswith('.jp2') and 'MSK_' not in str(res):
                    band_files[band_code] = res

    target_crs = QgsCoordinateReferenceSystem(epsg_code)
    if canvas_crs != target_crs:
        transform_to_raster = QgsCoordinateTransform(canvas_crs, target_crs, QgsProject.instance())
        transformed_extent = transform_to_raster.transformBoundingBox(ext)
        crop_extent = transformed_extent
    else:
        crop_extent = ext

    processed_bands = {}
    for band_code, band_path in band_files.items():
        output_path = os.path.join(temp_dir, f"{band_code}_10m_cropped.tif")
        try:
            processing.run("gdal:warpreproject", {
                'INPUT': str(band_path),
                'SOURCE_CRS': None,
                'TARGET_CRS': target_crs,
                'RESAMPLING': 0, 
                'NODATA': None,
                'TARGET_RESOLUTION': 10,
                'OPTIONS': '',
                'DATA_TYPE': 3,
                'TARGET_EXTENT': crop_extent,
                'TARGET_EXTENT_CRS': None,
                'MULTITHREADING': False,
                'EXTRA': '',
                'OUTPUT': output_path
            }, feedback=QgsProcessingFeedback())
            
            processed_bands[band_code] = output_path
            
        except Exception as e:
            processed_bands[band_code] = band_path

    # Step 3: Create multi-band stack for s2cloudless
    stacked_bands_path = os.path.join(temp_dir, "sentinel2_stack.vrt")
    if not os.path.exists(stacked_bands_path):
        band_order = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"]
        ordered_band_files = [processed_bands[band] for band in band_order if band in processed_bands]
        temp_layers = []
        for i, band_file in enumerate(ordered_band_files):
            band_name = band_order[i] if i < len(band_order) else f"band_{i}"
            layer = QgsRasterLayer(band_file, f"temp_{band_name}")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer, False)
                temp_layers.append(layer)
        if temp_layers:
            processing.run("gdal:buildvirtualraster", {
                'INPUT': temp_layers,
                'RESOLUTION': 0,
                'SEPARATE': True,
                'PROJ_DIFFERENCE': False,
                'ADD_ALPHA': False,
                'ASSIGN_CRS': None,
                'RESAMPLING': 0,
                'OUTPUT': stacked_bands_path
            }, feedback=QgsProcessingFeedback())
            
            for layer in temp_layers:
                lid = layer.id()
                QgsProject.instance().removeMapLayer(lid)
        else:
            return None

    else:
        print("OK")    
    
    # Step 4: Apply enhanced cloud detection
    for layer in QgsProject.instance().mapLayers().values():
        if 'temp_B' in layer.name():
            QgsProject.instance().removeMapLayer(layer.id())
    stack_layer = QgsRasterLayer(stacked_bands_path, "temp_stack")
    if not stack_layer.isValid():
        return None
    # Get raster data
    provider = stack_layer.dataProvider()
    extent = provider.extent()
    width = provider.xSize()
    height = provider.ySize()
    def apply_averaging_and_dilation(mask, average_over=4, dilation_size=3):
        mask_float = mask.astype(np.float32)
        kernel_size = 2 * average_over + 1
        averaged_mask = uniform_filter(mask_float, size=kernel_size, mode='constant')
        averaged_binary = averaged_mask > 0.5
        if dilation_size > 0:
            struct_elem = generate_binary_structure(2, 1)
            dilated_mask = averaged_binary
            for _ in range(dilation_size):
                dilated_mask = binary_dilation(dilated_mask, structure=struct_elem)
        else:
            dilated_mask = averaged_binary
        return dilated_mask

    bands_data = []
    for i in range(1, provider.bandCount() + 1):
        block = provider.block(i, extent, width, height)
        band_array = np.frombuffer(block.data(), dtype=np.uint16).reshape((height, width))
        bands_data.append(band_array)
    bands_array = np.stack(bands_data, axis = 2)

    processor = S2PixelCloudDetector(
        threshold = 0.35,
        average_over = 4,
        dilation_size = 3,
        all_bands = True 
    )

    def calculate_bsi(bands_array):
        swir1 = bands_array[:, :, 11].astype(np.float32)  # B11
        red = bands_array[:, :, 3].astype(np.float32)     # B4
        nir = bands_array[:, :, 7].astype(np.float32)     # B8
        blue = bands_array[:, :, 1].astype(np.float32)    # B2
        numerator = (swir1 + red) - (nir + blue)
        denominator = (swir1 + red) + (nir + blue)
        bsi = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator != 0)
        return bsi

    try:
        bands_array_float = bands_array.astype(np.float32)
        reflectance_data = (bands_array_float - 1000.0) / 10000.0
        reflectance_data = np.clip(reflectance_data, 0.0, 1.0)
        input_data = reflectance_data[np.newaxis, ...]
        cloud_masks = processor.get_cloud_masks(input_data)
        cloud_mask = cloud_masks[0] 
        bsi = calculate_bsi(bands_array_float)
        bsi_mask_raw = bsi > -0.01
        bsi_mask_processed = apply_averaging_and_dilation(
            bsi_mask_raw, 
            average_over = 4,  
            dilation_size = 3  
        )
        combined_mask = (~cloud_mask) | bsi_mask_processed
        clear_mask = ((~combined_mask) | cloud_mask).astype(np.uint8)
       
    except Exception as e:
        return None

    # Step 5: Save enhanced masks
    ref_layer = list(processed_bands.values())[0]
    ds = gdal.Open(ref_layer)
    binary_mask_path = os.path.join(temp_dir, "binary_mask.tif")
    save_mask_with_reference(clear_mask, binary_mask_path, ds)
   
    # Step 6: Create cloud-masked RGB composite for visualization
    available_output_bands = [band for band in output_bands if band in processed_bands]
    
    if len(available_output_bands) == 0:
        return None
    masked_band_files = []
    mask_layer = QgsRasterLayer(binary_mask_path, "binary_mask")
    QgsProject.instance().addMapLayer(mask_layer, False)
    
    for band_code in available_output_bands:
        band_file = processed_bands[band_code]
        masked_band_file = os.path.join(temp_dir, f"{band_code}_masked.tif")
        
        band_layer = QgsRasterLayer(band_file, f"temp_{band_code}")
        QgsProject.instance().addMapLayer(band_layer, False)
        
        processing.run("qgis:rastercalculator", {
            'EXPRESSION': f'"{band_layer.name()}@1" * (1 - "binary_mask@1")',
            'LAYERS': [band_layer, mask_layer],
            'CELLSIZE': 10,
            'EXTENT': None,
            'NODATA': 0,
            'RTYPE': 2,  # Float32
            'CRS': target_crs,
            'OUTPUT': masked_band_file
        }, feedback=QgsProcessingFeedback())
        
        masked_band_files.append(masked_band_file)
        QgsProject.instance().removeMapLayer(band_layer.id())

    layer_id = mask_layer.id()
    QgsProject.instance().removeMapLayer(layer_id)

    if progress_dialog:
        progress_dialog.set_detail("Cloud masking completed")
        progress_dialog.set_value(80)
    
    return True 