document.addEventListener('DOMContentLoaded', () => {
  const departure = document.querySelector('input[name="departure_date"]');
  const returning = document.querySelector('input[name="return_date"]');
  if (departure && returning) {
    departure.addEventListener('change', () => {
      returning.min = departure.value;
      if (returning.value && returning.value <= departure.value) returning.value = '';
    });
  }
    const themeToggle = document.querySelector('#theme-toggle');
    const savedTheme = localStorage.getItem('roamwise-theme');
    if (savedTheme === 'dark') document.documentElement.dataset.theme = 'dark';
    if (themeToggle) {
      themeToggle.addEventListener('click', () => {
        const dark = document.documentElement.dataset.theme !== 'dark';
        document.documentElement.dataset.theme = dark ? 'dark' : 'light';
        localStorage.setItem('roamwise-theme', dark ? 'dark' : 'light');
      });
    }

    const mapElement = document.querySelector('#destination-map');
    if (mapElement && window.L && mapElement.dataset.lat) {
      const position = [Number(mapElement.dataset.lat), Number(mapElement.dataset.lng)];
      const map = L.map(mapElement).setView(position, 11);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
      L.marker(position).addTo(map).bindPopup(mapElement.dataset.name).openPopup();
    }

    const chart = document.querySelector('#spend-chart');
    if (chart && window.Chart) {
      const values = (chart.dataset.values || '').split(',').filter(Boolean).map(Number);
      const labels = (chart.dataset.labels || '').split(',').filter(Boolean);
      new Chart(chart, { type: 'bar', data: { labels, datasets: [{ label: 'Trip cost (INR)', data: values, backgroundColor: '#127c82', borderRadius: 6 }] }, options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } } });
    }

    const weather = document.querySelector('#destination-weather');
    if (weather && weather.dataset.lat) {
      fetch(`https://api.open-meteo.com/v1/forecast?latitude=${weather.dataset.lat}&longitude=${weather.dataset.lng}&current=temperature_2m,weather_code,wind_speed_10m`)
        .then(response => response.ok ? response.json() : Promise.reject())
        .then(data => { weather.textContent = `${Math.round(data.current.temperature_2m)}°C · wind ${Math.round(data.current.wind_speed_10m)} km/h`; })
        .catch(() => { weather.textContent = 'Weather unavailable right now'; });
    }

    const currency = document.querySelector('#currency-converter');
    if (currency) {
      currency.addEventListener('change', () => {
        const output = document.querySelector('#converted-price');
        const amount = Number(currency.dataset.inr);
        if (!output || !amount) return;
        const code = currency.value;
        fetch(`https://api.frankfurter.app/latest?from=INR&to=${code}`)
          .then(response => response.json())
          .then(data => { output.textContent = `${code} ${(amount * data.rates[code]).toFixed(2)}`; })
          .catch(() => { output.textContent = 'Conversion unavailable'; });
      });
    }
});
