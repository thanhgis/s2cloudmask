# -*- coding: utf-8 -*-
import os, platform, sys
import subprocess
import importlib.util
import ctypes
from qgis.PyQt.QtCore import QObject, pyqtSignal, QThread, QT_VERSION_STR
from qgis.PyQt.QtWidgets import QProgressDialog, QMessageBox, QApplication
from qgis.core import QgsMessageLog, Qgis

class DependencyInstaller(QObject):
    """Handle dependency installation with progress feedback"""
    
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    finished = pyqtSignal(bool)  # True if successful, False if failed
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.qtVersion = int(QT_VERSION_STR.split('.')[0])
        # Get Python version info
        self.py = sys.version_info
        
        # Determine compatible versions based on Python version
        self.REQUIRED_PACKAGES = {
            "pystac_client": None,  # No known incompatibility
            "numpy": (
                "1.21.6" if self.py < (3, 8) else
                "1.24.4" if self.py < (3, 9) else
                "1.26.4"
            ),
            # OpenCV compatibility (headless):
            "opencv-python-headless": (
                "4.5.5.64" if self.py < (3, 8) else
                "4.11.0.86"
            ),
            # Shapely:
            "shapely": (
                "1.8.5.post1" if self.py < (3, 8) else
                "2.0.4"
            ),
            "s2cloudless": None
        }

    def _ensure_pip_updated(self):
        """Ensure pip is installed and upgraded before installing packages"""
        import importlib.util
        python_path = self._get_python()
        local_packages_dir = os.path.join(os.path.expanduser("~"), ".qgis_packages")

        QgsMessageLog.logMessage("Checking for pip module...", "s2CloudMask", Qgis.Info)

        # Step 1: Try to import pip
        pip_available = importlib.util.find_spec("pip") is not None

        # Step 2: If not found, try to bootstrap pip using ensurepip
        if not pip_available:
            QgsMessageLog.logMessage("pip not found, attempting to bootstrap using ensurepip...", "s2CloudMask", Qgis.Warning)
            try:
                cmd = [python_path, "-m", "ensurepip", "--upgrade", "--user"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                pip_available = True
                QgsMessageLog.logMessage("Successfully bootstrapped pip using ensurepip", "s2CloudMask", Qgis.Info)
            except subprocess.CalledProcessError as e:
                QgsMessageLog.logMessage(f"ensurepip failed: {e.stderr}", "s2CloudMask", Qgis.Critical)
                return False

        # Step 3: Try upgrade strategies for pip (user-level, local dir, default)
        strategies = [
            {
                "description": "user directory",
                "cmd": [python_path, "-m", "pip", "install", "--upgrade", "pip", "--user"]
            },
            {
                "description": "local directory",
                "cmd": [python_path, "-m", "pip", "install", "--upgrade", "pip", "--target", local_packages_dir]
            },
            {
                "description": "default location",
                "cmd": [python_path, "-m", "pip", "install", "--upgrade", "pip"]
            }
        ]

        for strategy in strategies:
            QgsMessageLog.logMessage(f"Trying pip upgrade to {strategy['description']}...", "s2CloudMask", Qgis.Info)
            try:
                result = subprocess.run(strategy["cmd"], capture_output=True, text=True, check=True)
                QgsMessageLog.logMessage(f"Successfully upgraded pip to {strategy['description']}", "s2CloudMask", Qgis.Info)
                return True
            except subprocess.CalledProcessError as e:
                QgsMessageLog.logMessage(f"{strategy['description'].capitalize()} upgrade failed: {e.stderr}", "s2CloudMask", Qgis.Warning)

        QgsMessageLog.logMessage("All pip upgrade strategies failed, continuing with existing version", "s2CloudMask", Qgis.Warning)
        return pip_available

    def check_dependencies(self):
        """Check if all required dependencies are available"""
        missing_packages = []

        # Define package name mappings (install name -> import name)
        package_mappings = {
            "pystac_client": "pystac_client",
            "numpy": "numpy", 
            "opencv-python-headless": "cv2",
            "shapely": "shapely",
            "s2cloudless": "s2cloudless"
        }
        
        for package_name, required_version in self.REQUIRED_PACKAGES.items():
            import_name = package_mappings.get(package_name, package_name)
            try:
                # Try to import the package
                module = importlib.import_module(import_name)
                
                # Check version if specified
                if required_version and hasattr(module, '__version__'):
                    current_version = module.__version__
                    if not self._version_compatible(current_version, required_version):
                        missing_packages.append((package_name, required_version, current_version))
                        QgsMessageLog.logMessage(
                            f"Package {package_name} version mismatch: found {current_version}, need {required_version}",
                            "s2CloudMask", Qgis.Warning
                        )
                    else:
                        QgsMessageLog.logMessage(
                            f"Package {package_name} version {current_version} is compatible",
                            "s2CloudMask", Qgis.Info
                        )
                        
            except ImportError:
                missing_packages.append((package_name, required_version, None))
                QgsMessageLog.logMessage(
                    f"Package {package_name} (import as {import_name}) not found",
                    "s2CloudMask", Qgis.Warning
                )
        return missing_packages
            
    def _version_compatible(self, current, required):
        """Simple version compatibility check that compares only major.minor.patch (ignoring build numbers)"""
        try:
            def get_base_version(version_str):
                """Extract only major.minor.patch, ignoring build/post numbers"""
                import re
                # Extract first 3 numeric parts (major.minor.patch)
                parts = re.findall(r'\d+', version_str)
                # Take only first 3 parts for comparison
                base_parts = parts[:3] if len(parts) >= 3 else parts
                return '.'.join(base_parts)
            
            current_base = get_base_version(current)
            required_base = get_base_version(required)
            
            current_parts = [int(x) for x in current_base.split('.')]
            required_parts = [int(x) for x in required_base.split('.')]
            
            # Pad shorter version with zeros
            max_len = max(len(current_parts), len(required_parts))
            current_parts.extend([0] * (max_len - len(current_parts)))
            required_parts.extend([0] * (max_len - len(required_parts)))
            
            # Check if current version is >= required version (comparing only major.minor.patch)
            for i in range(max_len):
                if current_parts[i] > required_parts[i]:
                    return True
                elif current_parts[i] < required_parts[i]:
                    return False
            
            # Base versions are equal, consider compatible
            return True
            
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Version comparison failed for {current} vs {required}: {e}",
                "s2CloudMask", Qgis.Warning
            )
            return True
            
    def install_dependencies(self, parent_widget=None):
        """Install missing dependencies with progress dialog"""
        missing_packages = self.check_dependencies()
        
        if not missing_packages:
            QMessageBox.information(
                parent_widget,
                "Dependencies Check",
                "All required dependencies are already installed!"
            )
            return True
        
        # Show confirmation dialog
        package_list = "\n".join([f"- {pkg[0]} {pkg[1] or 'latest'}" for pkg in missing_packages])

        if self.qtVersion == 5: 
            reply = QMessageBox.question(
                parent_widget,
                "Install Dependencies",
                f"The following packages need to be installed:\n\n{package_list}\n\nProceed with installation?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply != QMessageBox.Yes:
                return False
        elif self.qtVersion == 6: 
            reply = QMessageBox.question(
                parent_widget,
                "Install Dependencies",
                f"The following packages need to be installed:\n\n{package_list}\n\nProceed with installation?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return False

        # Create and show progress dialog (add 1 for pip upgrade step)
        progress_dialog = QProgressDialog("Upgrading pip...", "Cancel", 0, len(missing_packages) + 1, parent_widget)
        progress_dialog.setWindowTitle("s2CloudMask - Installing Dependencies")
        progress_dialog.setModal(True)
        progress_dialog.show()
        
        # Connect signals
        self.progress_updated.connect(progress_dialog.setValue)
        self.status_updated.connect(progress_dialog.setLabelText)
        
        # First, upgrade pip
        if progress_dialog.wasCanceled():
            return False
        
        self.status_updated.emit("Upgrading pip...")
        QApplication.processEvents()
        
        self._ensure_pip_updated()  # Always try to upgrade pip, even if it fails
        self.progress_updated.emit(1)
        QApplication.processEvents()
        
        # Then install packages
        success = True
        for i, (package_name, required_version, current_version) in enumerate(missing_packages):
            if progress_dialog.wasCanceled():
                success = False
                break
            
            self.status_updated.emit(f"Installing {package_name}...")
            QApplication.processEvents()
            
            if not self._install_single_package(package_name, required_version):
                success = False
                QMessageBox.critical(
                    parent_widget,
                    "Installation Failed",
                    f"Failed to install {package_name}. Please check the QGIS Python Console for details."
                )
                break
            
            self.progress_updated.emit(i + 2)  # +2 because we already did pip upgrade
            QApplication.processEvents()
        
        progress_dialog.close()
        
        if success:
            # Configure package priority after installation
            self._configure_package_priority()
            QMessageBox.information(
                parent_widget,
                "Installation Complete",
                "All dependencies have been installed successfully!\n\nYou may need to restart QGIS for all changes to take effect."
            )
        
        return success
        
    def _install_single_package(self, package_name, required_version):
        """Install a single package using multiple strategies"""
        python_path = self._get_python()
        pkg_spec = f"{package_name}=={required_version}" if required_version else package_name
        
        QgsMessageLog.logMessage(f"Installing {pkg_spec}...", "s2CloudMask", Qgis.Info)
        
        # Strategy 1: Install to user directory
        try:
            cmd = [python_path, "-m", "pip", "install", pkg_spec, "--user"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            QgsMessageLog.logMessage(f"Successfully installed {package_name} to user directory", "s2CloudMask", Qgis.Info)
            return True
        except subprocess.CalledProcessError as e:
            QgsMessageLog.logMessage(f"User install failed for {package_name}: {e.stderr}", "s2CloudMask", Qgis.Warning)
        
        # Strategy 2: Install to local packages directory
        try:
            local_packages_dir = os.path.join(os.path.expanduser("~"), ".qgis_packages")
            if not os.path.exists(local_packages_dir):
                os.makedirs(local_packages_dir)
            
            cmd = [python_path, "-m", "pip", "install", pkg_spec, "--target", local_packages_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            QgsMessageLog.logMessage(f"Successfully installed {package_name} to local directory", "s2CloudMask", Qgis.Info)
            return True
        except subprocess.CalledProcessError as e:
            QgsMessageLog.logMessage(f"Local install failed for {package_name}: {e.stderr}", "s2CloudMask", Qgis.Warning)
        
        # Strategy 3: Install normally (may require admin rights on Windows)
        try:
            cmd = [python_path, "-m", "pip", "install", pkg_spec]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            QgsMessageLog.logMessage(f"Successfully installed {package_name} to default location", "s2CloudMask", Qgis.Info)
            return True
        except subprocess.CalledProcessError as e:
            QgsMessageLog.logMessage(f"Default install failed for {package_name}: {e.stderr}", "s2CloudMask", Qgis.Critical)
            return False
    
    def _get_python(self):
        """Get the correct Python executable path"""
        if platform.system() == "Windows":
            qgis_app_path = os.path.dirname(sys.executable)
            possible_python = os.path.join(qgis_app_path, "python3.exe")
            if os.path.exists(possible_python):
                return possible_python
        return sys.executable
    
    def _get_qgis_python_root(self):
        """Get QGIS Python root directory"""
        if platform.system() == "Windows":
            qgis_bin_dir = os.path.dirname(sys.executable)  # ...\QGIS 3.x\bin
            qgis_root = os.path.dirname(qgis_bin_dir)       # ...\QGIS 3.x
            python_root = os.path.join(qgis_root, "apps", "Python37")
            if os.path.isdir(python_root):
                return python_root
        return None
    
    def _configure_package_priority(self):
        """Configure Python paths so QGIS can find installed packages"""
        import site
        
        # Add user site-packages to the beginning of sys.path
        user_site = site.getusersitepackages()
        if os.path.exists(user_site) and user_site not in sys.path:
            sys.path.insert(1, user_site)
            QgsMessageLog.logMessage(f"Added user site-packages to path: {user_site}", "s2CloudMask", Qgis.Info)
        
        # Add local packages directory
        local_packages_dir = os.path.join(os.path.expanduser("~"), ".qgis_packages")
        if os.path.exists(local_packages_dir) and local_packages_dir not in sys.path:
            insert_pos = 2 if user_site in sys.path[:2] else 1
            sys.path.insert(insert_pos, local_packages_dir)
            QgsMessageLog.logMessage(f"Added local packages to path: {local_packages_dir}", "s2CloudMask", Qgis.Info)
        
        # Create a .pth file for persistent path configuration
        try:
            plugin_dir = os.path.dirname(__file__)
            pth_file = os.path.join(plugin_dir, "custom_packages.pth")
            with open(pth_file, 'w') as f:
                if os.path.exists(local_packages_dir):
                    f.write(local_packages_dir + '\n')
                f.write(user_site + '\n')
            QgsMessageLog.logMessage(f"Created path file: {pth_file}", "s2CloudMask", Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Could not create path file: {e}", "s2CloudMask", Qgis.Warning)


def check_and_install_dependencies(parent_widget=None):
    """Convenience function to check and install dependencies"""
    installer = DependencyInstaller()
    return installer.install_dependencies(parent_widget)


def configure_import_paths():
    """Configure import paths without installing packages"""
    installer = DependencyInstaller()
    installer._configure_package_priority()


def get_missing_dependencies():
    """Get list of missing dependencies without installing"""
    installer = DependencyInstaller()
    return installer.check_dependencies()