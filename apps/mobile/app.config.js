// Adds to app.json what depends on files that may not be there yet.
const fs = require("fs");
const path = require("path");

// Firebase's Android config, which push alerts (an SOS reaching the owner with the app closed) need on Android. It is not committed: its
// API key is meant to be restricted in the Google Cloud console, and a key in a repository cannot be taken back. A cloud build gets the file
// from the GOOGLE_SERVICES_JSON file secret (EAS puts the secret's file on disk and sets the variable to its path); a build on your own
// machine uses ./google-services.json if you have put it there. Without either the app still builds, just without push on Android.
const LOCAL = "./google-services.json";

module.exports = ({ config }) => {
  const fromSecret = process.env.GOOGLE_SERVICES_JSON;
  if (fromSecret && fs.existsSync(fromSecret)) {
    config.android = { ...config.android, googleServicesFile: fromSecret };
  } else if (fs.existsSync(path.join(__dirname, LOCAL))) {
    config.android = { ...config.android, googleServicesFile: LOCAL };
  }
  return config;
};
