import { colors, spacing, tapTarget, typography } from "@fleettms/design-tokens";
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  useColorScheme,
  View,
  type TextInputProps,
} from "react-native";

export function useTheme() {
  return useColorScheme() === "dark" ? colors.dark : colors.light;
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

export function Screen({ children }: { children: ReactNode }) {
  const t = useTheme();
  return <View style={[styles.screen, { backgroundColor: t.bg }]}>{children}</View>;
}

export function Title({ children }: { children: ReactNode }) {
  const t = useTheme();
  return <Text style={[styles.title, { color: t.text }]}>{children}</Text>;
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  const t = useTheme();
  return <Text style={[styles.body, { color: muted ? t.muted : t.text }]}>{children}</Text>;
}

export function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <Text accessibilityRole="alert" style={[styles.body, { color: colors.alert }]}>
      {message}
    </Text>
  );
}

export function Input(props: TextInputProps & { label: string }) {
  const t = useTheme();
  const { label, ...rest } = props;
  return (
    <View style={styles.field}>
      <Text style={[styles.label, { color: t.muted }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={t.muted}
        style={[styles.input, { color: t.text, borderColor: t.muted, backgroundColor: t.surface }]}
        {...rest}
      />
    </View>
  );
}

export function Button({
  label,
  onPress,
  kind = "primary",
  busy,
  disabled,
}: {
  label: string;
  onPress: () => void;
  kind?: "primary" | "secondary" | "danger";
  busy?: boolean;
  disabled?: boolean;
}) {
  const t = useTheme();
  const bg = kind === "primary" ? colors.brand : "transparent";
  const fg = kind === "primary" ? "#fff" : kind === "danger" ? colors.alert : t.text;
  const border = kind === "primary" ? colors.brand : kind === "danger" ? colors.alert : t.muted;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || busy}
      style={[
        styles.button,
        { backgroundColor: bg, borderColor: border, opacity: disabled || busy ? 0.5 : 1 },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={[styles.buttonText, { color: fg }]}>{label}</Text>
      )}
    </Pressable>
  );
}

export const styles = StyleSheet.create({
  screen: { flex: 1, padding: spacing.md, gap: spacing.md, justifyContent: "center" },
  title: { fontSize: typography.title, fontWeight: "700" },
  body: { fontSize: typography.base },
  field: { gap: spacing.xs },
  label: { fontSize: 14 },
  input: {
    minHeight: tapTarget,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: spacing.md,
    fontSize: typography.large,
  },
  button: {
    minHeight: tapTarget,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  buttonText: { fontSize: typography.large, fontWeight: "600" },
});
