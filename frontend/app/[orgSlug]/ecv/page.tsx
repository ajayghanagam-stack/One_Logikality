"use client";

/**
 * ECV dashboard placeholder (US-3.4 target).
 *
 * The real ECV dashboard — overall score, Documents / Section Scores /
 * Items-to-Review tabs, severity classification, sticky action bar
 * (US-3.5 – 3.13) — lands in the next slices. For now this page is the
 * redirect target for the upload → pipeline-progress hand-off, and
 * surfaces just enough of the packet to confirm the route worked end
 * to end.
 *
 * `?packet={uuid}` is how the upload page hands control off. Hitting
 * /ecv without a packet param falls back to a "nothing to show yet"
 * state — will be replaced by a packet-history list in a later slice.
 */

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";
import { LOAN_PROGRAMS } from "@/lib/rules";

type PacketView = {
  id: string;
  declared_program_id: string;
  status: string;
  current_stage: string | null;
  started_processing_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export default function EcvPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const { ready } = useRequireRole(
    ["customer_admin", "customer_user"],
    `/${orgSlug}`,
  );
  const { token } = useAuth();

  const [packet, setPacket] = useState<PacketView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/packets/${packetId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          let detail: string | undefined;
          try {
            detail = (await res.json())?.detail;
          } catch {
            // non-json response — fall through to status-code message
          }
          throw new ApiError(
            res.status,
            detail,
            detail ?? `Couldn't load packet (${res.status}).`,
          );
        }
        const data: PacketView = await res.json();
        if (!cancelled) setPacket(data);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? (err.detail ?? `Couldn't load packet (${err.status}).`)
            : "Couldn't load packet.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, packetId]);

  if (!ready) return null;

  if (!packetId) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>ECV Dashboard</h1>
        <p style={emptyStyle}>
          Nothing to show yet. Upload a packet to see ECV results.
        </p>
        <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
          Upload a packet
        </Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 800 }}>
      <h1 style={titleStyle}>ECV Dashboard</h1>
      <p style={subtitleStyle}>
        Full ECV scoring, document inventory, and items-to-review ship in the
        next release. For now this confirms your packet finished processing.
      </p>

      {error ? (
        <div role="alert" style={errorBoxStyle}>
          {error}
        </div>
      ) : packet ? (
        <PacketCard packet={packet} />
      ) : (
        <p style={emptyStyle}>Loading…</p>
      )}
    </div>
  );
}

function PacketCard({ packet }: { packet: PacketView }) {
  const program = LOAN_PROGRAMS[packet.declared_program_id];
  return (
    <div style={cardStyle}>
      <dl style={metaListStyle}>
        <Row label="Packet ID" value={packet.id} mono />
        <Row
          label="Program"
          value={program?.label ?? packet.declared_program_id}
        />
        <Row label="Status" value={packet.status} badge />
        {packet.started_processing_at ? (
          <Row
            label="Started"
            value={new Date(packet.started_processing_at).toLocaleString()}
          />
        ) : null}
        {packet.completed_at ? (
          <Row
            label="Completed"
            value={new Date(packet.completed_at).toLocaleString()}
          />
        ) : null}
      </dl>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  badge,
}: {
  label: string;
  value: string;
  mono?: boolean;
  badge?: boolean;
}) {
  return (
    <div style={rowStyle}>
      <dt style={labelStyle}>{label}</dt>
      <dd
        style={{
          ...valueStyle,
          ...(mono ? monoStyle : null),
          ...(badge ? {} : null),
        }}
      >
        {badge ? <span style={statusPillStyle}>{value}</span> : value}
      </dd>
    </div>
  );
}

/* ----- styles -------------------------------------------------------- */

const titleStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 4px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: "0 0 24px",
};

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  padding: "22px 24px",
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
};

const metaListStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  margin: 0,
  padding: 0,
};

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "8px 12px",
  background: chrome.muted,
  borderRadius: 6,
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  fontWeight: 600,
  letterSpacing: 0.3,
  textTransform: "uppercase",
  margin: 0,
};

const valueStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.charcoal,
  margin: 0,
};

const monoStyle: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
  fontSize: 11,
};

const statusPillStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  padding: "2px 8px",
  borderRadius: 10,
  background: "#D1FAE5",
  color: "#065F46",
  border: "1px solid #A7F3D0",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const emptyStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: "0 0 16px",
};

const errorBoxStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 13,
};

const linkBtnStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "9px 18px",
  fontSize: 13,
  fontWeight: 600,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 6,
  textDecoration: "none",
  fontFamily: typography.fontFamily.primary,
};
