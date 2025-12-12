import React from 'react';
import { User, Briefcase, RefreshCw } from 'lucide-react';
import { PERSONAS } from '../utils/constants';

const ControlPanel = ({ activePersona, setActivePersona, onReset }) => {
  return (
    <div className="w-full max-w-md bg-white p-4 rounded-t-xl shadow-sm border-b flex justify-between items-center z-10">
      <div className="flex gap-2">
        <button 
          onClick={() => setActivePersona(PERSONAS.STUDENT)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${activePersona.id === 'student' ? 'bg-green-100 text-green-800 border border-green-200' : 'text-gray-500 hover:bg-gray-50'}`}
        >
          <User size={16} /> Student
        </button>
        <button 
          onClick={() => setActivePersona(PERSONAS.OWNER)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${activePersona.id === 'owner' ? 'bg-blue-100 text-blue-800 border border-blue-200' : 'text-gray-500 hover:bg-gray-50'}`}
        >
          <Briefcase size={16} /> Vendor
        </button>
      </div>
      <button onClick={onReset} className="text-red-500 hover:bg-red-50 p-2 rounded-full">
        <RefreshCw size={18} />
      </button>
    </div>
  );
};

export default ControlPanel;