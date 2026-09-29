/**
 * The admin section's navigation.
 *
 * DESIGN_SYSTEM.md section 6: "Left navigation 208 px, content max width
 * 1100 px, left aligned. Below 768 px the navigation becomes a top tab bar."
 * Those are two arrangements rather than two styles, so they are two elements
 * and one list of links -- the same split `DataTable` makes for the same
 * reason.
 *
 * Plain anchors to hash routes rather than buttons that call `navigate`: a link
 * is what this is, so it is reachable by keyboard, announced as a link, and
 * openable in a new tab.
 *
 * The current page is marked with `aria-current="page"` *and* a rule -- section
 * 3 requires that a state never be carried by colour alone.
 */
import { ADMIN_NAV } from "../../lib/constants";
import { routeHref } from "../../lib/router";

interface AdminNavProps {
  path: string;
}

export function AdminNav({ path }: AdminNavProps) {
  return (
    <>
      {/* Sidebar, 208 px, at md and up. */}
      <nav
        aria-label="Admin sections"
        className="hidden w-52 shrink-0 border-r border-rule bg-surface md:block"
      >
        <ul className="sticky top-14 flex flex-col gap-1 p-3">
          {ADMIN_NAV.map((item) => {
            const current = path === item.path;
            return (
              <li key={item.path}>
                <a
                  href={routeHref(item.path)}
                  aria-current={current ? "page" : undefined}
                  className={`flex min-h-[44px] items-center rounded-control px-3 font-sans text-ui-label focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-marine ${
                    current
                      ? "bg-marine-wash font-semibold text-marine"
                      : "text-ink-soft hover:bg-paper hover:text-ink"
                  }`}
                >
                  {item.label}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Top tab bar below md. */}
      <nav
        aria-label="Admin sections"
        className="border-b border-rule bg-surface md:hidden"
      >
        <ul className="flex gap-1 overflow-x-auto px-3">
          {ADMIN_NAV.map((item) => {
            const current = path === item.path;
            return (
              <li key={item.path}>
                <a
                  href={routeHref(item.path)}
                  aria-current={current ? "page" : undefined}
                  className={`inline-flex h-11 items-center whitespace-nowrap border-b-2 px-3 font-sans text-ui-label focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-marine ${
                    current
                      ? "border-marine font-semibold text-marine"
                      : "border-transparent text-ink-soft hover:text-ink"
                  }`}
                >
                  {item.label}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
