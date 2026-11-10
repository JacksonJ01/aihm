# AIHuMo

This repository contains two separate applications.

## Main Web App

The existing Next.js/TypeScript web application is in `MainWebApp/`.
Run web-app commands from that directory:

```powershell
cd MainWebApp
npm install
npm run dev
```

For Vercel, set the project **Root Directory** to `MainWebApp`.

The web annotation studio is the shared responsive surface for desktop, tablet, and phone. It can load a video from the device, import portable session/feature JSON, navigate frames, edit layered annotations, and export annotation JSON. The separate standalone mobile folder has been retired so there is one web workflow to maintain.

For phone access away from home, deploy `MainWebApp` to an HTTPS host such as Vercel and open that public URL on the phone. `localhost` is only reachable from the computer running the development server; it is not a public address.

## Python Annotation App

The PyQt6 processing and annotation application is in `mainApp/`.
See [mainApp/README.md](mainApp/README.md) for setup and run instructions.

The two applications have separate dependencies and runtime paths.
