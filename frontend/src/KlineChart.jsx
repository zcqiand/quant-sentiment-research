import React, { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

// ECharts 日 K + MA5/MA20 + 成交量（红涨绿跌 A 股配色）
export default function KlineChart({ kline }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !kline?.length) return undefined
    const chart = echarts.init(ref.current)
    const dates = kline.map((k) => String(k.date).slice(0, 10))
    const candles = kline.map((k) => [k.open, k.close, k.low, k.high])
    const volumes = kline.map((k) => k.volume)

    const maCalc = (n) =>
      kline.map((_, i) =>
        i < n - 1 ? null : kline.slice(i - n + 1, i + 1).reduce((s, k) => s + k.close, 0) / n
      )

    chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 60, right: 20, top: 10, height: '58%' },
        { left: 60, right: 20, top: '74%', height: '16%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, boundaryGap: true, axisLine: { lineStyle: { color: '#444' } } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#222' } } },
        { gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], top: '93%', height: 18, start: 40, end: 100 },
      ],
      series: [
        {
          name: '日K',
          type: 'candlestick',
          data: candles,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: { color: '#e24242', color0: '#1db460', borderColor: '#e24242', borderColor0: '#1db460' },
        },
        { name: 'MA5', type: 'line', data: maCalc(5), xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', lineStyle: { width: 1, color: '#f5a623' } },
        { name: 'MA20', type: 'line', data: maCalc(20), xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', lineStyle: { width: 1, color: '#4a90e2' } },
        { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: '#3a5a7a' } },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [kline])

  return <div ref={ref} className="kline-chart" />
}
