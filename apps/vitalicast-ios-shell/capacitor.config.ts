import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.hutchstack.vitalicast',
  appName: 'Vitalicast',
  webDir: 'www',
  server: {
    url: 'http://localhost:3000',
    cleartext: true
  }
};

export default config;
