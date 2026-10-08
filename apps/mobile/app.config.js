// Adds to app.json what depends on files that may not be there yet.
const fs = require("fs");
const path = require("path");

// Firebase's Android config, which push alerts (an SOS reaching the owner with the app closed) need on Android. It holds no secret,
// so it is committed beside this file. Without it the app still builds, just without push on Android.
const GOOGLE_SERVICES = "./google-services.json";

module.exports = ({ config }) => {
  if (fs.existsSync(path.join(__dirname, GOOGLE_SERVICES))) {
    config.android = { ...config.android, googleServicesFile: GOOGLE_SERVICES };
  }
  return config;
};
