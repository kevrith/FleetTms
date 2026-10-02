import { fromByteArray, toByteArray } from "base64-js";

export const toB64 = (bytes: Uint8Array): string => fromByteArray(bytes);
export const fromB64 = (text: string): Uint8Array => toByteArray(text);
export const utf8 = (text: string): Uint8Array => new TextEncoder().encode(text);
export const unutf8 = (bytes: Uint8Array): string => new TextDecoder().decode(bytes);
