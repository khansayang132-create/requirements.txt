import { useEffect, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";
import { IDENTITIES, useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { short } from "@/lib/wallet";
import { Icon, type IconName } from "../ui/Icon";
import { focusRing } from "../ui/styles";
import { TopDrawer } from "../ui/TopDrawer";
import { openWallet, WalletPanel } from "./WalletPanel";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Overview", icon: "home" },
  { to: "/agreements", label: "Agreements", icon: "list" },
  { to: "/sponsor", label: "Sponsor", icon: "sponsor" },
  { to: "/worker", label: "Worker", icon: "worker" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

const Logo = () => (
  <Link to="/" className={cn("flex items-center gap-2 rounded-xl", focusRing)}>
    <span className="grid size-8 place-items-center rounded-xl bg-violet-600 text-sm font-black text-white">D</span>
    <span className="text-base font-bold tracking-tight text-neutral-100">DONE</span>
  </Link>
);

export const MockBadge = () => <span className="rounded-lg bg-violet-600 px-2 py-0.5 text-xs font-bold text-white">MOCK</span>;

function WalletButton() {
  const wallet = useStore((s) => s.wallet);
  const name = IDENTITIES.find((i) => i.key === wallet)?.name;
  return (
    <button type="button" onClick={openWallet}
      className={cn("inline-flex min-h-10 items-center gap-2 rounded-xl border px-3 text-sm", focusRing,
        wallet ? "border-line font-mono text-neutral-200 hover:bg-surface-2" : "border-violet-500/50 font-semibold text-violet-300 hover:bg-violet-600/10")}>
      <Icon name="wallet" className="size-4" />
      {wallet ? <>{name && <span className="font-sans text-neutral-400">{name}</span>}{short(wallet)}</> : "Connect"}
    </button>
  );
}

/** Fake latency would be dishonest; in mock mode the ping reads "mock". */
function ClusterStatus() {
  const mock = useStore((s) => s.mock);
  const cluster = useStore((s) => s.cluster);
  return (
    <span className="inline-flex items-center gap-2 text-xs text-neutral-400">
      <span className={cn("size-2 rounded-full", mock ? "bg-violet-500" : "bg-amber-500")} />
      <span className="font-mono">{cluster === "devnet" ? "Devnet" : "Mainnet"}</span>
      <span className="font-mono text-neutral-500">{mock ? "local" : "no program"}</span>
    </span>
  );
}

export function Layout({ children, wide }: { children: ReactNode; wide?: boolean }) {
  const { mock, wallet, balances } = useStore((s) => s);
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  const balance = wallet ? formatUsdc(balances[wallet] ?? 0n) : null;

  return (
    <div className="min-h-dvh bg-black">
      <TopDrawer />
      {/* Desktop left nav */}
      <nav aria-label="Main" className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-surface p-4 md:flex">
        <div className="px-2 py-2"><Logo /></div>
        <ul className="mt-8 space-y-1">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} end={n.to === "/"}
                className={({ isActive }) => cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors", focusRing,
                  isActive ? "bg-violet-600/10 text-violet-300" : "text-neutral-400 hover:bg-surface-2 hover:text-neutral-200")}>
                <Icon name={n.icon} className="size-[18px]" />{n.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="mt-auto rounded-xl border border-line-soft bg-surface-2 p-3"><ClusterStatus /></div>
      </nav>

      {/* Top bar (desktop) / header (mobile) */}
      <header className="sticky top-0 z-20 border-b border-line bg-black/80 backdrop-blur md:pl-64">
        <div className="flex h-14 items-center justify-between gap-3 px-4 md:px-8">
          <div className="md:hidden"><Logo /></div>
          <div className="hidden items-center gap-4 md:flex">
            <ClusterStatus />
            {balance && <span className="font-mono text-xs tabular-nums text-neutral-300">{balance} USDC</span>}
          </div>
          <div className="flex items-center gap-2">
            {mock && <MockBadge />}
            <WalletButton />
          </div>
        </div>
      </header>

      <main className={cn("px-4 pb-24 pt-4 md:pb-12 md:pl-64 md:pt-8", wide && "lg:pr-[440px]")}>
        <div className="mx-auto max-w-6xl md:px-8">{children}</div>
      </main>

      {/* Mobile bottom nav */}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-5 rounded-t-2xl border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"}
            className={({ isActive }) => cn("flex flex-col items-center justify-center gap-1 rounded-xl text-[10px] font-medium", focusRing,
              isActive ? "text-violet-400" : "text-neutral-400")}>
            <Icon name={n.icon} />{n.label}
          </NavLink>
        ))}
      </nav>

      <WalletPanel />
    </div>
  );
}

export const PageHeader = ({ title, sub, action }: { title: string; sub?: ReactNode; action?: ReactNode }) => (
  <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0">
      <h1 className="text-2xl font-bold tracking-tight text-neutral-100 md:text-3xl">{title}</h1>
      {sub && <p className="mt-1 text-sm text-neutral-400">{sub}</p>}
    </div>
    {action}
  </div>
);
