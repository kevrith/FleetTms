import {
  BarChart3,
  MapPinned,
  MessageCircleQuestion,
  Mail,
  Server,
  Radio,
  ShieldAlert,
  Trophy,
  Briefcase,
  Building2,
  FileText,
  Handshake,
  Package,
  Siren,
  Settings,
  Truck,
  Users,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  /** Permission (from /auth/me) needed to see this item; with a list, any one is enough. Omit for everyone. */
  permission?: string | string[];
  /** Only for platform admins (people who run FleetTms itself). */
  platform?: boolean;
}

// Navigation per masterplan Section 6. Items appear as their sprint ships; until then they
// are shown only to roles that will use them.
export const navItems: NavItem[] = [
  { path: "/", label: "Home", icon: BarChart3 },
  {
    path: "/jobs",
    label: "Jobs & Dispatch",
    icon: Briefcase,
    permission: ["trips.view", "jobs.manage"],
  },
  { path: "/map", label: "Live map", icon: MapPinned, permission: "livemap.view" },
  { path: "/alerts", label: "Alerts", icon: ShieldAlert, permission: "alerts.view" },
  { path: "/scorecards", label: "Driver scorecards", icon: Trophy, permission: "reports.view" },
  { path: "/tracking", label: "Trackers & alerts", icon: Radio, permission: "livemap.view" },
  { path: "/vehicles", label: "Vehicles", icon: Truck, permission: "vehicles.view" },
  { path: "/trips", label: "Trips", icon: FileText, permission: "trips.view" },
  {
    path: "/clients",
    label: "Clients & Debts",
    icon: Handshake,
    permission: ["clients.manage", "finance.view"],
  },
  {
    path: "/expenses",
    label: "Expenses",
    icon: Wallet,
    permission: ["finance.view", "floats.manage", "vehicles.view"],
  },
  {
    path: "/workshop",
    label: "Workshop",
    icon: Wrench,
    permission: ["workshop.manage", "vehicles.view"],
  },
  {
    path: "/incidents",
    label: "Incidents & SOS",
    icon: Siren,
    permission: ["incidents.manage", "sos.respond", "vehicles.view"],
  },
  { path: "/leases", label: "Leases & Finance", icon: Building2, permission: "finance.view" },
  { path: "/staff", label: "Staff & Payroll", icon: Users, permission: "staff.view" },
  { path: "/suppliers", label: "Suppliers", icon: Package, permission: "workshop.manage" },
  { path: "/portal", label: "My leased lorries", icon: Building2, permission: "lease.view_own" },
  { path: "/messages", label: "Driver messages", icon: Mail, permission: "messages.send" },
  {
    path: "/ask",
    label: "Ask a question",
    icon: MessageCircleQuestion,
    permission: ["reports.view", "finance.view", "alerts.view"],
  },
  { path: "/platform", label: "Platform console", icon: Server, platform: true },
  { path: "/reports", label: "Reports", icon: BarChart3, permission: "reports.view" },
  { path: "/settings", label: "Settings", icon: Settings },
];
