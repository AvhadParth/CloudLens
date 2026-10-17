/* Logo, the hero "lens" graphic and all icons, drawn as SVG so they stay sharp at any size. */

export function Logo({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="logo-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#cfe1ff" />
          <stop offset="1" stopColor="#4c8df6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="#111a2e" />
      <rect x="0.500" y="0.500" width="31" height="31" rx="8.500" fill="none" stroke="#ffffff" strokeOpacity="0.140" />
      <circle cx="14.500" cy="14.500" r="6.500" fill="none" stroke="url(#logo-ring)" strokeWidth="2.400" />
      <path d="M19.500 19.500l4.500 4.500" stroke="url(#logo-ring)" strokeWidth="2.400" strokeLinecap="round" />
    </svg>
  )
}

/** Concentric rings with a soft core: the "lens" behind the homepage headline. */
export function LensOrb({ className }) {
  return (
    <svg className={className} viewBox="0 0 600 600" aria-hidden="true">
      <defs>
        <radialGradient id="orb-core">
          <stop offset="0" stopColor="#4c8df6" stopOpacity="0.260" />
          <stop offset="0.600" stopColor="#4c8df6" stopOpacity="0.060" />
          <stop offset="1" stopColor="#4c8df6" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="orb-ring" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.550" />
          <stop offset="0.500" stopColor="#6ea8ff" stopOpacity="0.180" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.020" />
        </linearGradient>
      </defs>
      <circle cx="300" cy="300" r="290" fill="url(#orb-core)" />
      <g fill="none" stroke="url(#orb-ring)">
        <circle cx="300" cy="300" r="120" strokeWidth="1.500" />
        <circle cx="300" cy="300" r="185" strokeWidth="1" />
        <circle cx="300" cy="300" r="250" strokeWidth="1" />
      </g>
      <g className="orb-spin">
        <circle cx="300" cy="300" r="185" fill="none" stroke="#6ea8ff" strokeOpacity="0.450" strokeWidth="1.500" strokeDasharray="2 14" />
        <circle cx="485" cy="300" r="4" fill="#e5604f" />
        <circle cx="300" cy="115" r="3" fill="#8fb8ff" />
      </g>
      <g className="orb-spin orb-spin-slow">
        <circle cx="300" cy="50" r="3.500" fill="#1ca88d" />
        <circle cx="123" cy="477" r="3" fill="#e5604f" />
      </g>
    </svg>
  )
}

const KIND_ART = {
  idle: <path d="M8 11h9l-9 11h9M20 7h5l-5 6h5" />,
  oversized: (
    <>
      <rect x="5" y="5" width="22" height="22" rx="5" />
      <rect x="13.500" y="15.500" width="7" height="7" rx="1.500" fill="currentColor" stroke="none" />
    </>
  ),
  always_on_dev: <path d="M23 19.500A9.500 9.500 0 1 1 13 6.500a7.500 7.500 0 0 0 10 13z" />,
  unattached_storage: (
    <>
      <ellipse cx="16" cy="9" rx="9" ry="4" />
      <path d="M7 9v14c0 2.200 4 4 9 4s9-1.800 9-4V9M7 16c0 2.200 4 4 9 4s9-1.800 9-4" />
    </>
  ),
}

export function KindIcon({ kind, size = 44 }) {
  return (
    <span className="kind-icon" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        {KIND_ART[kind]}
      </svg>
    </span>
  )
}

const ICONS = {
  home: <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  save: (
    <>
      <circle cx="12" cy="12" r="8.500" />
      <path d="M12 7.500v9M14.500 9.800c-.6-.8-1.500-1.200-2.500-1.200-1.400 0-2.400.7-2.400 1.700 0 2.300 5 1 5 3.300 0 1-1.100 1.700-2.600 1.700-1.100 0-2.100-.4-2.700-1.200" />
    </>
  ),
  cloud: <path d="M7 18.500a4 4 0 0 1-.6-7.960A5.500 5.500 0 0 1 17 10a4.250 4.250 0 0 1 .5 8.500z" />,
  bills: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2.500" />
      <path d="M4 10h16M8 3v4M16 3v4" />
    </>
  ),
  ask: <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-8l-4 4v-4H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />,
  history: (
    <>
      <circle cx="12" cy="12" r="8.500" />
      <path d="M12 7.500V12l3 2" />
    </>
  ),
  plug: <path d="M9 3v5M15 3v5M6.500 8h11v3.500a5.500 5.500 0 0 1-11 0zM12 17v4" />,
  check: <path d="M5 12.500l4.500 4.500L19 7.500" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
}

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.800" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  )
}

/* Provider logos are the companies' own marks (from Wikimedia Commons), adapted for the
   dark theme. They are trademarks of their owners and are used only to show which clouds
   CloudLens can read. */
const LOGOS = {
  aws: { mark: '/logos/aws.svg', name: 'Amazon Web Services', short: 'AWS', width: 304, height: 182 },
  azure: { mark: '/logos/azure.svg', name: 'Microsoft Azure', short: 'Azure', width: 96, height: 96 },
  gcp: { mark: '/logos/google-cloud.svg', name: 'Google Cloud', short: 'Google Cloud', width: 36, height: 28 },
}

/** The provider's logo in a square tile. */
export function ProviderMark({ id, size = 46 }) {
  const logo = LOGOS[id]
  return (
    <span className={`provider-mark provider-mark-${id}`} style={{ width: size, height: size }}>
      <img src={logo.mark} alt={logo.name} width={logo.width} height={logo.height} decoding="async" />
    </span>
  )
}

/** Logo plus name on one line, for tables and small labels. */
export function ProviderBadge({ id }) {
  const logo = LOGOS[id]
  return (
    <span className="provider-badge">
      <img src={logo.mark} alt="" width={logo.width} height={logo.height} decoding="async" />
      {logo.short}
    </span>
  )
}

/** A row of the three logos as they appear on the companies' own sites. */
export function ProviderLogos({ className = '' }) {
  return (
    <ul className={`provider-logos ${className}`} aria-label="Works with Amazon Web Services, Microsoft Azure and Google Cloud">
      <li>
        <img src="/logos/aws.svg" alt="Amazon Web Services" width="304" height="182" className="logo-aws" decoding="async" />
      </li>
      <li>
        <img src="/logos/azure.svg" alt="" width="96" height="96" className="logo-azure-mark" decoding="async" />
        <span>Microsoft Azure</span>
      </li>
      <li>
        <img src="/logos/google-cloud-wordmark.svg" alt="Google Cloud" width="181" height="28" className="logo-gcp" decoding="async" />
      </li>
    </ul>
  )
}
