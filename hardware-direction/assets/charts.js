(function () {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Radar: 四条候选路线多维度对比 ---
  var radar = echarts.init(document.getElementById('chart-routes'), null, { renderer: 'svg' });
  radar.setOption({
    animation: false,
    color: [accent, accent2, '#C9B6FF', accent + '99'],
    tooltip: { trigger: 'item', appendToBody: true, backgroundColor: bg2, borderColor: rule, textStyle: { color: ink } },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: muted, fontSize: 12 }
    },
    radar: {
      indicator: [
        { name: '集成成本', max: 5 },
        { name: '故障安全', max: 5 },
        { name: '免App/免联网', max: 5 },
        { name: '许可合规', max: 5 },
        { name: '生态可持续', max: 5 }
      ],
      radius: '62%',
      splitNumber: 5,
      splitLine: { lineStyle: { color: rule } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: rule } },
      axisName: { color: muted, fontSize: 12 }
    },
    series: [{
      type: 'radar',
      data: [
        {
          name: 'API-bridge（官方，已实现）',
          value: [5, 3, 2, 4, 4],
          symbol: 'circle', symbolSize: 5,
          areaStyle: { opacity: 0.12 },
          lineStyle: { width: 2, color: accent },
          itemStyle: { color: accent }
        },
        {
          name: 'PyDGLab-WS BLE 直连',
          value: [4, 4, 5, 3, 2],
          symbol: 'circle', symbolSize: 5,
          areaStyle: { opacity: 0.12 },
          lineStyle: { width: 2, color: accent2 },
          itemStyle: { color: accent2 }
        },
        {
          name: '郊狼官方协议直连',
          value: [2, 4, 4, 2, 4],
          symbol: 'circle', symbolSize: 5,
          areaStyle: { opacity: 0.12 },
          lineStyle: { width: 2, color: '#C9B6FF' },
          itemStyle: { color: '#C9B6FF' }
        },
        {
          name: 'Coyote Game Hub(REST)',
          value: [3, 3, 4, 3, 3],
          symbol: 'circle', symbolSize: 5,
          areaStyle: { opacity: 0.10 },
          lineStyle: { width: 2, color: accent + '99' },
          itemStyle: { color: accent + '99' }
        }
      ]
    }]
  });
  window.addEventListener('resize', function () { radar.resize(); });
})();