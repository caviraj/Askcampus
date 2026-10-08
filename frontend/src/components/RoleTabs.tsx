/**
 * Role switcher tablist for the authentication screen.
 *
 * Implements accessible ARIA tabs (role="tablist", role="tab") for Student and Staff,
 * with visible focus rings and minimum 44px touch targets.
 */
interface RoleTabsProps {
  role: "student" | "staff";
  onChange: (role: "student" | "staff") => void;
  disabled?: boolean;
}

export function RoleTabs({ role, onChange, disabled = false }: RoleTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Account type"
      className="inline-flex h-11 w-full rounded-control border border-rule bg-surface p-1"
    >
      <button
        type="button"
        role="tab"
        id="tab-student"
        aria-selected={role === "student"}
        aria-controls="auth-panel"
        disabled={disabled}
        onClick={() => onChange("student")}
        className={`flex flex-1 items-center justify-center rounded-control font-sans text-ui-label font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-marine ${
          role === "student"
            ? "bg-marine font-semibold text-white shadow-sm"
            : "text-ink-soft hover:text-ink"
        }`}
      >
        Student
      </button>

      <button
        type="button"
        role="tab"
        id="tab-staff"
        aria-selected={role === "staff"}
        aria-controls="auth-panel"
        disabled={disabled}
        onClick={() => onChange("staff")}
        className={`flex flex-1 items-center justify-center rounded-control font-sans text-ui-label font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-marine ${
          role === "staff"
            ? "bg-marine font-semibold text-white shadow-sm"
            : "text-ink-soft hover:text-ink"
        }`}
      >
        Staff
      </button>
    </div>
  );
}
