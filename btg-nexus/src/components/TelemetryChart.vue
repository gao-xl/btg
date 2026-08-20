<script setup>
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import * as echarts from 'echarts'

const chartRef = ref(null)
const chartInstance = shallowRef(null)

const props = defineProps({
  heartRate: { type: Array, default: () => [] },
  imuAmplitude: { type: Array, default: () => [] },
  timeLabels: { type: Array, default: () => [] }
})

function initChart() {
  if (!chartRef.value) return
  chartInstance.value = echarts.init(chartRef.value, 'dark')

  const option = {
    grid: {
      top: 12,
      right: 12,
      bottom: 24,
      left: 44
    },
    xAxis: {
      type: 'category',
      data: props.timeLabels,
      axisLine: { lineStyle: { color: '#1A2230' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#4A5E78',
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace'
      },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'value',
      min: 40,
      max: 160,
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#4A5E78',
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace'
      },
      splitLine: {
        lineStyle: {
          color: 'rgba(6, 182, 212, 0.04)',
          type: 'dashed'
        }
      }
    },
    series: [
      {
        name: 'BPM',
        type: 'line',
        data: props.heartRate,
        smooth: 0.4,
        symbol: 'none',
        lineStyle: {
          color: '#06B6D4',
          width: 2
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(6, 182, 212, 0.15)' },
            { offset: 1, color: 'rgba(6, 182, 212, 0.01)' }
          ])
        }
      },
      {
        name: 'IMU',
        type: 'line',
        data: props.imuAmplitude,
        smooth: 0.4,
        symbol: 'none',
        lineStyle: {
          color: '#D946EF',
          width: 1.5,
          type: 'dashed'
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(217, 70, 239, 0.08)' },
            { offset: 1, color: 'rgba(217, 70, 239, 0.0)' }
          ])
        }
      }
    ],
    legend: {
      show: true,
      bottom: 0,
      textStyle: {
        color: '#7A8FA3',
        fontSize: 10,
        fontFamily: 'JetBrains Mono, monospace'
      },
      itemWidth: 12,
      itemHeight: 2
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(13, 19, 26, 0.95)',
      borderColor: '#1A2230',
      textStyle: {
        color: '#C8D6E0',
        fontSize: 11,
        fontFamily: 'JetBrains Mono, monospace'
      }
    }
  }

  chartInstance.value.setOption(option)
}

function handleResize() {
  chartInstance.value?.resize()
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance.value?.dispose()
})

watch(() => [props.heartRate, props.imuAmplitude], () => {
  if (chartInstance.value) {
    chartInstance.value.setOption({
      xAxis: { data: props.timeLabels },
      series: [
        { data: props.heartRate },
        { data: props.imuAmplitude }
      ]
    })
  }
}, { deep: true })
</script>

<template>
  <div ref="chartRef" class="w-full h-full min-h-[240px]"></div>
</template>