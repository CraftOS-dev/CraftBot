import { createRoot } from 'react-dom/client';
import { StrictMode } from 'react';
import { App } from './app/App.tsx';
import { ApprovalDialog, Notices } from './support.tsx';
import './app.css';
import { UpdateNotice } from './UpdateNotice.tsx';

const root = document.getElementById('root');
if (!root) throw new Error('Missing app root');
createRoot(root).render(<StrictMode><App /><Notices /><ApprovalDialog /><UpdateNotice /></StrictMode>);
