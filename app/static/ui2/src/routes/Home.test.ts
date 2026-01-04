import { render, screen } from '@testing-library/svelte';
import Home from './Home.svelte';

describe('Home route', () => {
  it('renders the app title', () => {
    render(Home);
    expect(screen.getByRole('heading', { name: 'deception-ai' })).toBeInTheDocument();
  });

  it('shows the create game section', () => {
    render(Home);
    expect(screen.getByRole('heading', { name: 'Create new game' })).toBeInTheDocument();
  });
});

