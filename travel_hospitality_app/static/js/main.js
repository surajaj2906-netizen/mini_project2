document.addEventListener('DOMContentLoaded', () => {
  const departure = document.querySelector('input[name="departure_date"]');
  const returning = document.querySelector('input[name="return_date"]');
  if (departure && returning) {
    departure.addEventListener('change', () => {
      returning.min = departure.value;
      if (returning.value && returning.value <= departure.value) returning.value = '';
    });
  }
});
