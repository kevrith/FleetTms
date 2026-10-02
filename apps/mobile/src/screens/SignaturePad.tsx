import { useRef, useState } from "react";
import { PanResponder, View } from "react-native";
import { Button, useTheme } from "../ui";

export type Strokes = number[][][];

/**
 * A box to sign in with a finger. The pen strokes are kept as lists of points (they are drawn into the invoice's proof
 * of delivery on the server) and shown here as dots along the line.
 */
export function SignaturePad({ onChange }: { onChange: (strokes: Strokes | null) => void }) {
  const t = useTheme();
  const [strokes, setStrokes] = useState<Strokes>([]);
  const current = useRef<number[][]>([]);
  const all = useRef<Strokes>([]);

  const commit = (next: Strokes) => {
    all.current = next;
    setStrokes(next);
    onChange(next.length ? next : null);
  };

  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false, // keep the finger on the pad even inside a scrolling form
      onPanResponderGrant: (e) => {
        current.current = [
          [Math.round(e.nativeEvent.locationX), Math.round(e.nativeEvent.locationY)],
        ];
        commit([...all.current, current.current]);
      },
      onPanResponderMove: (e) => {
        const last = current.current[current.current.length - 1];
        const x = Math.round(e.nativeEvent.locationX);
        const y = Math.round(e.nativeEvent.locationY);
        if (last && Math.abs(last[0]! - x) + Math.abs(last[1]! - y) < 3) return;
        if (current.current.length >= 400) return;
        current.current = [...current.current, [x, y]];
        commit([...all.current.slice(0, -1), current.current]);
      },
    }),
  ).current;

  return (
    <View style={{ gap: 8 }}>
      <View
        {...pan.panHandlers}
        accessibilityLabel="Signature box"
        style={{
          height: 180,
          borderRadius: 12,
          borderWidth: 2,
          borderColor: t.muted,
          backgroundColor: "#ffffff",
          overflow: "hidden",
        }}
      >
        {strokes.flatMap((stroke, s) =>
          stroke.map((p, i) => (
            <View
              key={`${s}-${i}`}
              pointerEvents="none"
              style={{
                position: "absolute",
                left: (p[0] ?? 0) - 2,
                top: (p[1] ?? 0) - 2,
                width: 5,
                height: 5,
                borderRadius: 3,
                backgroundColor: "#111827",
              }}
            />
          )),
        )}
      </View>
      <Button
        label="Clear the signature"
        kind="secondary"
        onPress={() => commit([])}
        disabled={strokes.length === 0}
      />
    </View>
  );
}
