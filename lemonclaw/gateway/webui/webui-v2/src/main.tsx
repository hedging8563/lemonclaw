import { render } from 'preact';
import { App } from './App';
import './styles/global.css';
import './styles/markdown.css';

if (localStorage.getItem('lc_theme') === 'light') {
  document.documentElement.setAttribute('data-theme', 'light');
}

render(<App />, document.getElementById('app')!);