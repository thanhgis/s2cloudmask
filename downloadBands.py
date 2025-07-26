# downloadBands.py
"""
Sentinel-2 Cloud Masking Module using enhanced s2cloudless algorithm
ThanhGIS / ThanhNV All rights reserved 2025
Enhanced version with adaptive thresholding and cloud shadow detection
"""
import requests, os
from qgis.PyQt.QtWidgets import QMessageBox
        
def get_access_token(cdseId, cdseSecret):
    token_response = requests.post("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token", data = {
        "grant_type": "password",
        "client_id": "cdse-public",
        "username": cdseId,
        "password": cdseSecret,
    })
    if token_response.status_code != 200:
        return None
    token = token_response.json().get("access_token")
    return token


def getAllFiles(product_id, access_token, node_path="", folder_path=""):
    headers = {"Authorization": f"Bearer {access_token}"}
    if node_path:
        nodes_url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id}){node_path}/Nodes"
    else:
        nodes_url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/Nodes"
    response = requests.get(nodes_url, headers=headers)
    if response.status_code != 200:
        QMessageBox.warning(None, 'Connection error', f'There is an error occurred during retrieving files from the server. Feel free to try again. \n\nResponse status code: {response.status_code}')
        return []
    response_data = response.json()
    nodes = response_data.get('result', [])
    files = []
    for node in nodes:
        node_name = node.get('Name', '')
        node_id_current = node.get('Id', '')
        children_number = node.get('ChildrenNumber', 0)
        current_folder_path = os.path.join(folder_path, node_name) if folder_path else node_name
        if children_number > 0:
            new_node_path = f"{node_path}/Nodes({node_id_current})"
            subfiles = getAllFiles(product_id, access_token, new_node_path, current_folder_path)
            files.extend(subfiles)
        else:
            files.append({
                'name': node_name,
                'id': node_id_current,
                'folder_path': folder_path,
                'download_url': f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id}){node_path}/Nodes({node_id_current})/$value" if node_path else f"https://download.dataspace.copernicus.eu/odata/v1/Products({product_id})/Nodes({node_id_current})/$value"
            })

    return files

def downloadL1CBands(cdseId, cdseSecret, product_name, download_dir, band_name = None, progress_dialog = None, progress_start = 0, progress_end=100):
    required_bands = {
        "B01": {"res": "20m", "name": "Coastal Aerosol"},
        "B02": {"res": "10m", "name": "Blue"},
        "B03": {"res": "10m", "name": "Green"},
        "B04": {"res": "10m", "name": "Red"},
        "B05": {"res": "20m", "name": "Red Edge 1"},
        "B06": {"res": "20m", "name": "Red Edge 2"},
        "B07": {"res": "20m", "name": "Red Edge 3"},
        "B08": {"res": "10m", "name": "NIR"},
        "B8A": {"res": "20m", "name": "Narrow NIR"},
        "B09": {"res": "60m", "name": "Water Vapour"},
        "B10": {"res": "60m", "name": "Cirrus"},
        "B11": {"res": "20m", "name": "SWIR 1"},
        "B12": {"res": "20m", "name": "SWIR 2"},
        "TCI": {"res": "10m", "name": "True Color Image"}
    }
    if progress_dialog:
        progress_dialog.set_detail("Checking existing files...")
        progress_dialog.set_value(progress_start)
    
    granule_path = os.path.join(download_dir, f"{product_name}.SAFE", 'GRANULE')
    found_bands = []
    for dirpath, dirnames, filenames in os.walk(granule_path): 
        for band in required_bands.keys():
            matching_files = [f for f in filenames if f.endswith(f'{band}.jp2') and 'MSK_' not in f and band in f]
            for file in matching_files:
                if len(file) == 30: 
                    full_path = os.path.join(dirpath, file)
                    if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                        found_bands.append(full_path)
    if band_name:
        target_bands = [band_name] if band_name in required_bands else []
        if not target_bands:
            return []
    else:
        target_bands = [b for b in required_bands.keys() if b != 'TCI']  

    existing_target_bands = []
    for band_path in found_bands:
        for target_band in target_bands:
            if f"{target_band}.jp2" in os.path.basename(band_path):
                existing_target_bands.append(target_band)
                break
    
    if len(existing_target_bands) >= len(target_bands):
        if progress_dialog:
            progress_dialog.set_detail("All required bands already exist.")
            progress_dialog.set_value(progress_end)
        return found_bands
    
    if progress_dialog:
        progress_dialog.set_detail("Connecting to Copernicus Data Space...")
        current_progress = progress_start + (progress_end - progress_start) * 0.1
        progress_dialog.set_value(int(current_progress))
    
    if progress_dialog and progress_dialog.is_cancelled():
        return None
    
    access_token = get_access_token(cdseId, cdseSecret)
    search_url = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter=Name eq '{product_name}.SAFE'"
    headers = {"Authorization": f"Bearer {access_token}"}
    res_search = requests.get(search_url, headers=headers)

    if res_search.status_code != 200:
        QMessageBox.warning(None, 'Connection error', 'There is an error occurred on connecting to the server, might be caused by wrong username or password or due to internet connection. Feel free to check and try again.')
        return None
    
    search_data = res_search.json()
    products = search_data.get('value', [])

    if not products:
        if progress_dialog:
            progress_dialog.set_detail("Product not found on server")
        return None
    
    # Get product ID and file list
    product_id = products[0].get('Id')
    
    if progress_dialog:
        progress_dialog.set_detail("Retrieving file list...")
        current_progress = progress_start + (progress_end - progress_start) * 0.2
        progress_dialog.set_value(int(current_progress))
    
    all_files = getAllFiles(product_id, access_token)
    image_files = [f for f in all_files if f['name'].endswith('.jp2') and 'GRANULE' in f['folder_path']]
    
    if not image_files:
        if progress_dialog:
            progress_dialog.set_detail("No image files found")
        return []
    
    downloaded_files = []
    total_files_to_download = 0
    files_to_download = []
    
    # Prepare download list
    for file_info in image_files:
        file_name = file_info['name']
        folder_path = file_info['folder_path']
        band_id = None
        
        for band in target_bands:
            if f"{band}" in file_name or f"_{band}.jp2" in file_name:
                band_id = band
                break
        
        if band_id and band_id not in existing_target_bands:
            files_to_download.append({
                'file_info': file_info,
                'band_id': band_id,
                'file_name': file_name,
                'folder_path': folder_path
            })

    total_files_to_download = len(files_to_download)
    if total_files_to_download == 0:
        if progress_dialog:
            progress_dialog.set_detail("All required bands already exist")
            progress_dialog.set_value(progress_end)
        return found_bands

    download_progress_start = progress_start + (progress_end - progress_start) * 0.2
    download_progress_range = (progress_end - progress_start) * 0.8
    
    for i, download_info in enumerate(files_to_download):
        if progress_dialog and progress_dialog.is_cancelled():
            return None
        
        file_info = download_info['file_info']
        band_id = download_info['band_id']
        file_name = download_info['file_name']
        folder_path = download_info['folder_path']
        
        if progress_dialog:
            progress_dialog.set_detail(f"Downloading {required_bands[band_id]['name']} ({band_id})...")
            file_progress = (i / total_files_to_download) * download_progress_range
            progress_dialog.set_value(int(download_progress_start + file_progress))
        
        local_file_path = os.path.join(download_dir, folder_path, file_name)
        local_dir = os.path.dirname(local_file_path)
        os.makedirs(local_dir, exist_ok=True)
        file_url = file_info['download_url']
        
        try:
            response = requests.get(file_url, headers=headers, stream=True)
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(local_file_path, "wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        # Check for cancellation during download
                        if progress_dialog and progress_dialog.is_cancelled():
                            file.close()
                            if os.path.exists(local_file_path):
                                os.remove(local_file_path)  # Clean up partial file
                            return None
                            
                        if chunk:
                            file.write(chunk)
                            downloaded += len(chunk)
                            
                            # Update progress within current file download
                            if progress_dialog and total_size > 0:
                                file_completion = downloaded / total_size
                                current_file_progress = (i + file_completion) / total_files_to_download
                                total_progress = download_progress_start + (current_file_progress * download_progress_range)
                                progress_dialog.set_value(int(total_progress))
                
                file_size_mb = downloaded / (1024 * 1024)
                downloaded_files.append({
                    'band_id': band_id,
                    'name': file_name,
                    'local_path': local_file_path,
                    'folder_path': folder_path,
                    'resolution': required_bands[band_id]['res'],
                    'description': required_bands[band_id]['name'],
                    'size_mb': file_size_mb
                })
                
                if progress_dialog:
                    progress_dialog.set_detail(f"Downloaded {required_bands[band_id]['name']} ({file_size_mb:.1f} MB)")
                    
            else:
                error_msg = f'Connection issue. Response status code: {response.status_code}'
                if progress_dialog:
                    progress_dialog.set_detail(f"Error downloading {band_id}: {error_msg}")
                QMessageBox.warning(None, u'Connection issue.', f'There might be an issue with the internet connection or reading the data in the server. Feel free to try again after a few minutes or check your internet connection. \n\n{error_msg}')
                
        except Exception as e:
            error_msg = f"Error downloading {band_id}: {str(e)}"
            if progress_dialog:
                progress_dialog.set_detail(error_msg)

    # Final progress update
    if progress_dialog:
        if downloaded_files:
            progress_dialog.set_detail(f"Downloaded {len(downloaded_files)} band(s) successfully")
        else:
            progress_dialog.set_detail("Download completed")
        progress_dialog.set_value(progress_end)

    if downloaded_files:
        folders = {}
        for df in downloaded_files:
            folder = df['folder_path']
            if folder not in folders:
                folders[folder] = []
            folders[folder].append(df)
    
    return downloaded_files if downloaded_files else found_bands