import { I18nProvider } from '../shared/i18n/I18nProvider';
import GamePage from '../features/game/GamePage';

export default function App() {
  return <I18nProvider><GamePage /></I18nProvider>;
}
