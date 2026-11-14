// The rail row's and the mobile tab's icon, in a file of its own so the shell does not pull the whole portfolio page into the first load.
export function PortfolioIcon() {
  return <svg className="portfolio-icon" viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M4 20V10M10 20V5M16 20v-7M22 20H2" />
  </svg>;
}
