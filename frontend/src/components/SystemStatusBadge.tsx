import { AlertTriangle } from "lucide-react";
import type { SystemStatus } from "../lib/api";

/** Warning badge if environment requirements (such as Windows fonts) are incomplete. */
export function SystemStatusBadge({ status }: { status: SystemStatus | null }) {
  if (!status) return null;

  if (status.windows_fonts_complete === false) {
    return (
      <span
        className="flex items-center gap-1 text-xs text-amber-400"
        title={`Windows persona fonts incomplete: ${status.windows_fonts_present ?? 0}/${status.windows_fonts_required ?? 0} found`}
      >
        <AlertTriangle className="h-3.5 w-3.5" /> Fonts incomplete
      </span>
    );
  }

  return null;
}
