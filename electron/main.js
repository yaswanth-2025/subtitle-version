const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const express = require('express');
const fs = require('fs');

let mainWindow;
let backendProcess;
let mongoProcess;
let frontendServer;

const isDev = !app.isPackaged;
const isWindows = process.platform === 'win32';

// In packaged app, resources are in app.asar.unpacked
let appBundlePath;
if (isDev) {
    appBundlePath = path.resolve(__dirname, isWindows ? 'app-bundle-windows' : 'app-bundle');
} else {
    // For packaged apps, check app.asar.unpacked first
    const unpackedPath = path.resolve(process.resourcesPath, 'app.asar.unpacked', isWindows ? 'app-bundle-windows' : 'app-bundle');
    if (fs.existsSync(unpackedPath)) {
        appBundlePath = unpackedPath;
    } else {
        appBundlePath = path.resolve(process.resourcesPath, isWindows ? 'app-bundle-windows' : 'app-bundle');
    }
}

console.log('🔧 App bundle path:', appBundlePath);
console.log('🔧 Bundle exists:', fs.existsSync(appBundlePath));

// Check if Visual C++ Redistributable is needed (Windows only)
async function checkVCRedist() {
    if (!isWindows) return true;
    
    return new Promise((resolve) => {
        console.log('🔍 Checking Visual C++ Redistributable...');
        
        // Check registry for VC++ 2015-2022 runtime
        const checkCmd = 'reg query "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Installed 2>nul';
        
        const { exec } = require('child_process');
        exec(checkCmd, (error, stdout) => {
            if (error || !stdout.includes('0x1')) {
                console.log('⚠️  Visual C++ Redistributable may not be installed');
                console.log('   If MongoDB fails to start, install from:');
                console.log('   https://aka.ms/vs/17/release/vc_redist.x64.exe');
                resolve(true); // Continue anyway - don't block startup
            } else {
                console.log('✅ Visual C++ Redistributable already installed');
                resolve(true);
            }
        });
        
        // Don't block startup - timeout after 2 seconds
        setTimeout(() => {
            console.log('⏭️  Proceeding with startup...');
            resolve(true);
        }, 2000);
    });
}

function startMongoDB() {
    return new Promise((resolve) => {
        console.log('🗄️  Starting MongoDB...');
        
        const mongoPath = path.resolve(appBundlePath, 'mongodb', 'bin', isWindows ? 'mongod.exe' : 'mongod');
        const dataPath = path.resolve(app.getPath('userData'), 'mongodb-data');
        const logPath = path.resolve(app.getPath('userData'), 'mongodb.log');
        
        // Create data directory
        if (!fs.existsSync(dataPath)) {
            fs.mkdirSync(dataPath, { recursive: true });
        }
        
        if (!fs.existsSync(mongoPath)) {
            console.log('⚠️  MongoDB binary not found, using system MongoDB');
            resolve(false);
            return;
        }
        
        mongoProcess = spawn(mongoPath, [
            '--dbpath', dataPath,
            '--port', '27017',
            '--bind_ip', '127.0.0.1',
            '--noauth',
            '--logpath', logPath,
            '--quiet'
        ]);
        
        mongoProcess.stdout.on('data', (data) => {
            console.log(`MongoDB: ${data}`);
        });
        
        mongoProcess.stderr.on('data', (data) => {
            const msg = data.toString();
            if (msg.includes('waiting for connections')) {
                console.log('✅ MongoDB started');
                resolve(true);
            }
        });
        
        mongoProcess.on('error', (error) => {
            console.error('❌ MongoDB failed to start:', error.message);
            
            // Check if it's a DLL error
            if (isWindows && (error.message.includes('dll') || error.code === 'ENOENT')) {
                console.error('');
                console.error('⚠️  ERROR: ffmpeg.dll or other DLL not found');
                console.error('   This means Visual C++ Redistributable is not installed properly.');
                console.error('');
                console.error('   SOLUTION:');
                console.error('   1. Close this app');
                console.error('   2. Download and install:');
                console.error('      https://aka.ms/vs/17/release/vc_redist.x64.exe');
                console.error('   3. Restart this app');
                console.error('');
            }
            
            resolve(false);
        });
        
        mongoProcess.on('exit', (code, signal) => {
            if (code !== 0 && code !== null) {
                console.error(`❌ MongoDB exited with code ${code}`);
                
                if (isWindows && code === 3221225781) {  // 0xC0000135 = missing DLL
                    console.error('');
                    console.error('⚠️  ERROR CODE 0xC0000135: Missing DLL');
                    console.error('   ffmpeg.dll or vc_runtime140.dll not found');
                    console.error('');
                    console.error('   SOLUTION:');
                    console.error('   1. Download Visual C++ Redistributable:');
                    console.error('      https://aka.ms/vs/17/release/vc_redist.x64.exe');
                    console.error('   2. Run the installer');
                    console.error('   3. Restart this app');
                    console.error('');
                }
            }
        });
        
        setTimeout(() => resolve(true), 10000);
    });
}

function startFrontendServer() {
    return new Promise((resolve) => {
        const expressApp = express();
        const frontendPath = path.resolve(appBundlePath, 'frontend');
        
        expressApp.use(express.static(frontendPath));
        expressApp.get('*', (req, res) => {
            const indexPath = path.resolve(frontendPath, 'index.html');
            res.sendFile(indexPath);
        });
        
        frontendServer = expressApp.listen(5173, () => {
            console.log('✅ Frontend: http://localhost:5173');
            resolve();
        });
    });
}

function installDepsIfNeeded() {
    return new Promise((resolve, reject) => {
        const backendPath = path.resolve(appBundlePath, 'backend');
        const depsMarker = path.resolve(backendPath, '.deps_installed');
        
        if (fs.existsSync(depsMarker)) {
            console.log('✅ Dependencies already installed');
            resolve();
            return;
        }
        
        console.log('📦 Installing dependencies (first run - this will take 2-3 minutes)...');
        console.log('   Please wait, downloading Python packages from the internet...');
        
        const installCmd = isWindows 
            ? path.resolve(appBundlePath, 'install-deps.bat')
            : path.resolve(appBundlePath, 'install-deps.sh');
        
        if (!fs.existsSync(installCmd)) {
            console.error('❌ Install script not found:', installCmd);
            reject(new Error('Install script missing'));
            return;
        }
        
        const install = spawn(isWindows ? installCmd : 'bash', isWindows ? [] : [installCmd], {
            shell: isWindows,
            cwd: appBundlePath
        });
        
        let hasOutput = false;
        
        install.stdout.on('data', (data) => {
            hasOutput = true;
            console.log(`Install: ${data.toString()}`);
        });
        
        install.stderr.on('data', (data) => {
            hasOutput = true;
            console.log(`Install: ${data.toString()}`);
        });
        
        install.on('close', (code) => {
            if (code === 0 || fs.existsSync(depsMarker)) {
                console.log('✅ Dependencies installed successfully');
                resolve();
            } else {
                console.error(`❌ Dependency installation failed with code ${code}`);
                console.error('   Try running install-deps.bat manually as Administrator');
                reject(new Error(`Installation failed with code ${code}`));
            }
        });
        
        install.on('error', (error) => {
            console.error('❌ Failed to run install script:', error);
            reject(error);
        });
        
        // Longer timeout for pip installation (3 minutes)
        setTimeout(() => {
            if (!hasOutput) {
                console.error('❌ Installation timeout - no output received');
                console.error('   The install script may be stuck or failed to start');
                reject(new Error('Installation timeout'));
            } else if (!fs.existsSync(depsMarker)) {
                console.log('⚠️  Installation still in progress after 3 minutes');
                console.log('   Proceeding anyway, but backend may fail if not complete');
                resolve(); // Proceed anyway
            } else {
                resolve();
            }
        }, 180000); // 3 minutes
    });
}

function startBackend() {
    return new Promise((resolve, reject) => {
        console.log('🐍 Starting Python backend...');
        
        const backendPath = path.resolve(appBundlePath, 'backend');
        
        // Use bundled Python on Windows, system Python on Linux
        let pythonCmd;
        if (isWindows) {
            const bundledPython = path.resolve(appBundlePath, 'python', 'python.exe');
            if (fs.existsSync(bundledPython)) {
                pythonCmd = bundledPython;
                console.log('   ✅ Using bundled Python:', pythonCmd);
            } else {
                pythonCmd = 'python';
                console.log('   ⚠️  Bundled Python not found, trying system Python');
            }
        } else {
            pythonCmd = 'python3';
        }
        
        console.log('   Backend path:', backendPath);
        
        // Test if Python works
        const pythonTest = spawn(pythonCmd, ['--version'], { 
            shell: isWindows && pythonCmd === 'python' 
        });
        
        pythonTest.on('error', (error) => {
            console.error('❌ Python not available:', error.message);
            reject(new Error('Python not found'));
            return;
        });
        
        pythonTest.on('close', (code) => {
            if (code !== 0) {
                console.error('❌ Python test failed');
                reject(new Error('Python not working'));
                return;
            }
            
            console.log('   Starting Uvicorn server...');
            
            backendProcess = spawn(pythonCmd, [
                '-m', 'uvicorn',
                'main:app',
                '--host', '127.0.0.1',
                '--port', '8000'
            ], {
                cwd: backendPath,
                env: {
                    ...process.env,
                    MONGODB_URL: 'mongodb://127.0.0.1:27017',
                    DATABASE_NAME: 'srt_compare',
                    // Set Python paths for bundled Python
                    ...(isWindows && pythonCmd.includes('python.exe') ? {
                        PYTHONHOME: path.resolve(appBundlePath, 'python'),
                        PYTHONPATH: path.resolve(appBundlePath, 'python', 'Lib', 'site-packages')
                    } : {})
                },
                shell: isWindows && pythonCmd === 'python'
            });

            let backendStarted = false;

            backendProcess.stdout.on('data', (data) => {
                const msg = data.toString();
                console.log(`Backend: ${msg}`);
                if (msg.includes('Uvicorn running') || msg.includes('Application startup complete')) {
                    backendStarted = true;
                    resolve();
                }
            });

            backendProcess.stderr.on('data', (data) => {
                const msg = data.toString();
                console.log(`Backend: ${msg}`);
                
                // Check for common errors
                if (msg.includes('ModuleNotFoundError')) {
                    console.error('❌ Missing Python module - dependencies not installed');
                    console.error('   Run install-deps.bat as Administrator');
                }
                if (msg.includes('Address already in use')) {
                    console.error('❌ Port 8000 already in use');
                }
            });

            backendProcess.on('error', (error) => {
                console.error('❌ Backend error:', error);
                if (!backendStarted) {
                    reject(error);
                }
            });

            backendProcess.on('exit', (code) => {
                if (code !== 0 && !backendStarted) {
                    console.error(`❌ Backend exited with code ${code}`);
                    reject(new Error(`Backend exited with code ${code}`));
                }
            });

            // Timeout after 15 seconds
            setTimeout(() => {
                if (!backendStarted) {
                    console.log('⚠️  Backend timeout - proceeding anyway');
                    resolve();
                }
            }, 15000);
        });
    });
}

async function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        },
        show: false
    });

    mainWindow.loadFile(path.join(__dirname, 'loading.html'));
    mainWindow.show();

    try {
        // Check and install VC++ Redistributable first (Windows only)
        await checkVCRedist();
        
        await installDepsIfNeeded();
        await startMongoDB();
        await startBackend();
        await startFrontendServer();
        
        await new Promise(resolve => setTimeout(resolve, 2000));
        mainWindow.loadURL('http://localhost:5173');

    } catch (error) {
        console.error('Startup error:', error);
        mainWindow.loadFile(path.join(__dirname, 'error.html'));
    }

    mainWindow.on('closed', () => mainWindow = null);
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
    if (mongoProcess) mongoProcess.kill();
    if (backendProcess) backendProcess.kill();
    if (frontendServer) frontendServer.close();
    if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
    if (mongoProcess) mongoProcess.kill();
    if (backendProcess) backendProcess.kill();
    if (frontendServer) frontendServer.close();
});
