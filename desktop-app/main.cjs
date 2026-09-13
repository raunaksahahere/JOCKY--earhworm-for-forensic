const { app, BrowserWindow, dialog, session } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const PORT = 5000;
const HOST = '127.0.0.1';
let backend = null;
let mainWindow = null;
let logStream = null;

function backendExecutable() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', 'JOCKY-backend.exe');
  }
  return path.join(__dirname, '..', 'desktop', 'backend-dist', 'JOCKY-backend.exe');
}

function dashboardIndex() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'dashboard', 'index.html');
  }
  return path.join(__dirname, '..', 'dashboard', 'dist', 'index.html');
}

function logFile() {
  return path.join(app.getPath('userData'), 'jocky-backend.log');
}

function startBackend() {
  const exe = backendExecutable();
  if (!fs.existsSync(exe)) {
    throw new Error(`Bundled JOCKY backend was not found:\n${exe}`);
  }

  fs.mkdirSync(path.dirname(logFile()), { recursive: true });
  logStream = fs.createWriteStream(logFile(), { flags: 'a' });
  logStream.write(`\n--- JOCKY backend ${new Date().toISOString()} ---\n`);

  backend = spawn(exe, [], {
    windowsHide: true,
    cwd: path.dirname(exe),
    env: { ...process.env, JOCKY_PORT: String(PORT), JOCKY_HOST: HOST },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backend.stdout?.on('data', (data) => logStream?.write(data));
  backend.stderr?.on('data', (data) => logStream?.write(data));
  backend.on('error', (error) => logStream?.write(`Backend process error: ${error.stack || error}\n`));
  backend.on('exit', (code, signal) => logStream?.write(`Backend exited: code=${code} signal=${signal}\n`));
}

function waitForHealth(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;

  return new Promise((resolve, reject) => {
    const check = () => {
      if (Date.now() > deadline) {
        reject(new Error(`JOCKY backend did not become ready.\n\nBackend log: ${logFile()}`));
        return;
      }

      const request = http.get({ host: HOST, port: PORT, path: '/health', timeout: 1200 }, (res) => {
        res.resume();
        if (res.statusCode === 200) {
          resolve(true);
        } else {
          setTimeout(check, 300);
        }
      });

      request.on('error', () => setTimeout(check, 300));
      request.on('timeout', () => request.destroy());
    };

    check();
  });
}

function stopBackend() {
  if (!backend || backend.killed) return;
  try { backend.kill(); } catch (_) {}
  backend = null;
  try { logStream?.end(); } catch (_) {}
  logStream = null;
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'JOCKY — Digital Forensics Investigation Platform',
    backgroundColor: '#14161a',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  await mainWindow.loadFile(dashboardIndex());

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

async function boot() {
  // Electron's renderer loads the production static bundle directly from disk.
  // Node/npm are never required on the target PC.
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));

  startBackend();
  await waitForHealth();
  await createWindow();
}

app.whenReady().then(boot).catch(async (error) => {
  console.error(error);
  await dialog.showMessageBox({
    type: 'error',
    title: 'JOCKY could not start',
    message: 'JOCKY failed to start its bundled forensic engine.',
    detail: `${error.message}\n\nBackend log:\n${logFile()}`,
  });
  stopBackend();
  app.quit();
});

app.on('before-quit', stopBackend);
app.on('window-all-closed', () => {
  stopBackend();
  app.quit();
});
