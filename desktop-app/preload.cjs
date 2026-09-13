const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('jockyDesktop', {
  platform: process.platform,
  version: process.versions.electron,
});
