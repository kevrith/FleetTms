import type { PhotoKind, PhotoRef } from "@fleettms/types";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Location from "expo-location";
import { useRef, useState } from "react";
import { Image, Text, View } from "react-native";
import { api } from "./api";
import { Body, Button, ErrorText, errorMessage, useTheme } from "./ui";

const MIN_SHORT_SIDE = 640;

/** Where the phone is right now, or null if the person said no or there is no fix within a few seconds. */
async function currentPosition(): Promise<{ lat: number; lng: number } | null> {
  try {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (perm.status !== "granted") return null;
    const fix = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 6000)),
    ]);
    return fix ? { lat: fix.coords.latitude, lng: fix.coords.longitude } : null;
  } catch {
    return null;
  }
}

/**
 * Live camera only. There is deliberately no gallery picker anywhere in the app: every photo is taken on the spot,
 * stamped with the time and GPS position, and uploaded straight away (masterplan 5.4).
 */
export function CaptureScreen({
  kind,
  title,
  hint,
  guide,
  onDone,
  onCancel,
}: {
  kind: PhotoKind;
  title: string;
  hint: string;
  /** Draws a frame to line the odometer up in. */
  guide?: boolean;
  onDone: (photo: PhotoRef, localUri: string) => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const [shot, setShot] = useState<{ uri: string; takenAt: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!permission) return <View />;
  if (!permission.granted) {
    return (
      <View style={{ gap: 12 }}>
        <Title2>{title}</Title2>
        <Body>
          FleetTms needs the camera to take this photo. Photos cannot be chosen from the gallery.
        </Body>
        <Button label="Allow camera" onPress={requestPermission} />
        <Button label="Cancel" kind="secondary" onPress={onCancel} />
      </View>
    );
  }

  async function take() {
    setBusy(true);
    setError(null);
    try {
      const picture = await camera.current?.takePictureAsync({ quality: 0.7 });
      if (!picture) throw new Error("The camera did not take a photo. Try again.");
      if (Math.min(picture.width, picture.height) < MIN_SHORT_SIDE) {
        setError("That photo is too small to read. Move closer and try again.");
        return;
      }
      setShot({ uri: picture.uri, takenAt: new Date().toISOString() });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function usePhoto() {
    if (!shot) return;
    setBusy(true);
    setError(null);
    try {
      const where = await currentPosition();
      const photo = await api.uploadPhoto(
        { uri: shot.uri, name: "photo.jpg", type: "image/jpeg" },
        { kind, source: "camera", captured_at: shot.takenAt, lat: where?.lat, lng: where?.lng },
      );
      onDone(photo, shot.uri);
    } catch (e) {
      setError(errorMessage(e));
      setShot(null); // a rejected photo (too old, repeated) cannot be reused, so go back to the camera
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 12 }}>
      <Title2>{title}</Title2>
      <Body muted>{hint}</Body>
      {shot ? (
        <Image
          source={{ uri: shot.uri }}
          style={{ width: "100%", height: 320, borderRadius: 12 }}
          resizeMode="cover"
        />
      ) : (
        <View
          style={{ height: 320, borderRadius: 12, overflow: "hidden", backgroundColor: t.surface }}
        >
          <CameraView ref={camera} style={{ flex: 1 }} facing="back" />
          {guide && (
            <View
              pointerEvents="none"
              style={{
                position: "absolute",
                left: "10%",
                right: "10%",
                top: "30%",
                height: "40%",
                borderWidth: 3,
                borderColor: "#fff",
                borderRadius: 8,
              }}
            />
          )}
        </View>
      )}
      <ErrorText message={error} />
      {shot ? (
        <>
          <Button label="Use this photo" onPress={usePhoto} busy={busy} />
          <Button label="Retake" kind="secondary" onPress={() => setShot(null)} disabled={busy} />
        </>
      ) : (
        <Button label="Take photo" onPress={take} busy={busy} />
      )}
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </View>
  );
}

function Title2({ children }: { children: string }) {
  const t = useTheme();
  return <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>{children}</Text>;
}
