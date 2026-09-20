using AssetStudio;
using System;

namespace AssetStudioGUI
{
    class GUILogger : ILogger
    {
        public bool ShowErrorMessage = true;
        private Action<string> action;

        public GUILogger(Action<string> action)
        {
            this.action = action;
        }

        public void Log(LoggerEvent loggerEvent, string message)
        {
            switch (loggerEvent)
            {
                case LoggerEvent.Error:
                    ErrorLogged?.Invoke(message);
                    break;
                default:
                    action(message);
                    break;
            }
        }

        public event Action<string> ErrorLogged;
    }
}
