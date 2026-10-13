const whole = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const cents = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const shortDate = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const longDate = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const monthName = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const stamp = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export const money = (value) => whole.format(value)
export const moneyExact = (value) => cents.format(value)
export const percent = (value, digits = 0) => `${Number(value).toFixed(digits)}%`
export const day = (iso) => shortDate.format(new Date(iso))
export const fullDay = (iso) => longDate.format(new Date(iso))
export const month = (ym) => monthName.format(new Date(`${ym}-01`))
export const timestamp = (iso) => stamp.format(new Date(iso))

/** Everyday words for the technical labels in the data. */
export const ENVIRONMENT = { prod: 'Live', staging: 'Pre-launch', dev: 'Development', test: 'Testing' }
export const TYPE = { vm: 'server', database: 'database', storage: 'storage' }
export const firstName = (name) => name.trim().split(/\s+/)[0]
