import { useEffect, useState } from "react";
import { Linking } from "react-native";
import { api } from "../api";
import { Body, Button } from "../ui";

type Contact = {
  whatsapp: string | null;
  whatsapp_link: string | null;
  email: string | null;
  hours: string;
};

/** How to reach FleetTms support, when the channels have been set up. Needs a connection; shows nothing if there is none. */
export function SupportCard() {
  const [c, setC] = useState<Contact | null>(null);
  useEffect(() => {
    api
      .contact()
      .then(setC)
      .catch(() => setC(null));
  }, []);
  if (!c || (!c.whatsapp_link && !c.email)) return null;
  return (
    <>
      {c.whatsapp_link && (
        <Button
          kind="secondary"
          label={`WhatsApp support ${c.whatsapp ?? ""}`}
          onPress={() => void Linking.openURL(c.whatsapp_link!)}
        />
      )}
      {c.email && (
        <Button
          kind="secondary"
          label={`Email ${c.email}`}
          onPress={() => void Linking.openURL(`mailto:${c.email}`)}
        />
      )}
      <Body muted>{c.hours}. Never send a password or a code.</Body>
    </>
  );
}
