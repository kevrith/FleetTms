import type { InboxMessage } from "@fleettms/types";
import { useIsFocused } from "@react-navigation/native";
import { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView } from "react-native";
import { api } from "../api";
import { Body, ErrorText, errorMessage, Screen, Title } from "../ui";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-KE", {
    timeZone: "Africa/Nairobi",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/** Messages from the office: announcements to every driver, and notes about a job or trip. Reading one tells the office it was seen. */
export default function MessagesScreen() {
  const focused = useIsFocused();
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { messages: list } = await api.myMessages();
      setMessages(list);
      setError(null);
      // Opening the screen is reading: tell the office, but keep the NEW tag until the next visit.
      for (const m of list.filter((x) => !x.read_at)) await api.markMessageRead(m.id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (focused) void load();
  }, [focused, load]);

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ gap: 12, paddingVertical: 16 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}
      >
        <Title>Messages</Title>
        <ErrorText message={error} />
        {messages.length === 0 && !error && <Body muted>No messages from the office.</Body>}
        {messages.map((m) => (
          <Body key={m.id}>
            {m.read_at ? "" : "NEW  "}
            {m.from ?? "Office"}, {when(m.created_at)}
            {"\n"}
            {m.body}
          </Body>
        ))}
      </ScrollView>
    </Screen>
  );
}
