import * as FileSystem from "expo-file-system";
import * as SecureStore from "expo-secure-store";
import { toB64 } from "./bytes";
import type { FileAdapter } from "./store";
import type { KeyStore } from "./vault";

const KEY_NAME = "fleettms.vaultkey";
const DIR = `${FileSystem.documentDirectory ?? ""}fleettms/`;

export const keys: KeyStore = {
  get: () => SecureStore.getItemAsync(KEY_NAME),
  set: (v) => SecureStore.setItemAsync(KEY_NAME, v),
  clear: () => SecureStore.deleteItemAsync(KEY_NAME),
};

export const files: FileAdapter = {
  async read(name) {
    const info = await FileSystem.getInfoAsync(DIR + name);
    return info.exists
      ? FileSystem.readAsStringAsync(DIR + name, { encoding: FileSystem.EncodingType.UTF8 })
      : null;
  },
  async write(name, base64) {
    await FileSystem.makeDirectoryAsync(DIR, { intermediates: true });
    await FileSystem.writeAsStringAsync(DIR + name, base64, {
      encoding: FileSystem.EncodingType.UTF8,
    });
  },
  remove: (name) => FileSystem.deleteAsync(DIR + name, { idempotent: true }),
  removeAll: () => FileSystem.deleteAsync(DIR, { idempotent: true }),
  async writeTemp(name, bytes) {
    const uri = `${FileSystem.cacheDirectory}${name}`;
    await FileSystem.writeAsStringAsync(uri, toB64(bytes), {
      encoding: FileSystem.EncodingType.Base64,
    });
    return { uri, cleanup: () => FileSystem.deleteAsync(uri, { idempotent: true }) };
  },
};
