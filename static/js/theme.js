// simple theme toggle that stores preference in localStorage
(function(){
  const body = document.body;
  const btn = document.getElementById('themeToggle');
  const saved = localStorage.getItem('site-theme');

  if(saved === 'dark') body.classList.remove('theme-light'), body.classList.add('theme-dark');
  else body.classList.remove('theme-dark'), body.classList.add('theme-light');

  if(btn){
    btn.addEventListener('click', () => {
      if(body.classList.contains('theme-dark')){
        body.classList.remove('theme-dark'); body.classList.add('theme-light');
        localStorage.setItem('site-theme','light');
        btn.textContent = '🌙';
      } else {
        body.classList.remove('theme-light'); body.classList.add('theme-dark');
        localStorage.setItem('site-theme','dark');
        btn.textContent = '☀️';
      }
    });
  }
})();
