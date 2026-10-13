import { useApi } from '../api.js'
import { day, money, moneyExact, month, percent } from '../format.js'
import LineChart from '../components/LineChart.jsx'
import { Loader, PageHeader } from '../components/common.jsx'

const HISTORY_DAYS = 120
const PLAIN_METHOD = {
  'Baseline: repeat last week': 'Simple guess: copy last week',
  'Baseline: last 7-day average': 'Simple guess: average of last week',
}

export default function Bills({ summary }) {
  const forecast = useApi('/forecast')
  const evaluation = useApi('/evaluation')

  return (
    <>
      <PageHeader title="Your next bills">
        What you are likely to pay over the next three months if you keep everything as it is today.
      </PageHeader>
      <Loader requests={[forecast, evaluation, summary]}>
        {() => {
          const f = forecast.data
          const test = evaluation.data.forecast
          const dailySaving = (summary.data.open_monthly_saving + summary.data.approved_monthly_saving) / 30
          const history = f.history.slice(-HISTORY_DAYS)
          const pad = (n) => Array(n).fill(null)
          const dates = [...history.map((d) => d.date), ...f.forecast.map((d) => d.date)]

          const series = [
            { name: 'What you paid', color: 'var(--blue)', values: [...history.map((d) => d.cost), ...pad(f.forecast.length)] },
            {
              name: 'What we expect',
              color: 'var(--blue)',
              dashed: true,
              values: [...pad(history.length - 1), history.at(-1).cost, ...f.forecast.map((d) => d.cost)],
            },
          ]
          if (dailySaving > 0) {
            series.push({
              name: 'If you make every fix',
              color: 'var(--mint-deep)',
              dashed: true,
              values: [...pad(history.length), ...f.forecast.map((d) => d.cost - dailySaving)],
            })
          }
          const model = test.results.find((r) => r.is_model)
          const bestSimple = test.results.filter((r) => !r.is_model).sort((a, b) => a.mape - b.mape)[0]

          return (
            <>
              <ul className="months">
                {f.monthly.map((m, i) => (
                  <li key={m.month} className={`sticker ${['sticker-white', 'sticker-sky', 'sticker-sun'][i % 3]}`}>
                    <p className="sticker-label">{month(m.month)}</p>
                    <p className="sticker-number">{money(m.cost)}</p>
                    {dailySaving > 0 && (
                      <p className="sticker-note">
                        or <strong>{money(m.cost - dailySaving * m.days)}</strong> if you make every fix
                      </p>
                    )}
                  </li>
                ))}
              </ul>

              <section className="panel">
                <h2>Day by day</h2>
                <p className="panel-note">
                  The solid line is what you actually paid. The dashed line is our prediction, and the shaded band is
                  the range it will probably fall in.
                </p>
                <LineChart
                  dates={dates}
                  series={series}
                  band={{
                    name: 'Likely range',
                    low: [...pad(history.length), ...f.forecast.map((d) => d.low)],
                    high: [...pad(history.length), ...f.forecast.map((d) => d.high)],
                  }}
                  formatY={money}
                  formatX={day}
                  height={340}
                  label="Line chart of daily spending for the last four months followed by the prediction for the next three"
                />
              </section>

              <p className="callout">
                <strong>How much can you trust this?</strong> We hid three past two-month stretches, asked CloudLens to
                predict them, then checked. On average it was off by {percent(model.mape, 1)} a day, about{' '}
                {moneyExact(model.mae)}.
              </p>

              <details className="tech">
                <summary>Technical details: how the prediction was tested</summary>
                <p>
                  Method: {model.method}, trained on {f.trained_on_days} days of history. It was tested on{' '}
                  {test.folds.length} separate {test.holdout_days}-day periods it had not seen, against two methods
                  that use no machine learning.
                </p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Method</th>
                        <th scope="col" className="num">Average daily error (MAPE)</th>
                        <th scope="col" className="num">In dollars (MAE)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {test.results.map((r) => (
                        <tr key={r.method} className={r.is_model ? 'row-strong' : undefined}>
                          <th scope="row">{PLAIN_METHOD[r.method] ?? r.method}</th>
                          <td className="num">{percent(r.mape, 2)}</td>
                          <td className="num">{moneyExact(r.mae)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p>
                  {model.mape < bestSimple.mape
                    ? `The model's error is ${percent((1 - model.mape / bestSimple.mape) * 100)} lower than the best simple guess.`
                    : 'The model does not beat the best simple guess on this data.'}{' '}
                  The sample bill is much steadier than a real one, so expect bigger errors on real data.
                </p>
              </details>
            </>
          )
        }}
      </Loader>
    </>
  )
}
