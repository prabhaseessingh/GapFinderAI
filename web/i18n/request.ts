import {getRequestConfig} from 'next-intl/server';
import {defaultLocale, isAppLocale} from './config';

export default getRequestConfig(async ({requestLocale}) => {
  const requested = await requestLocale;
  const locale = requested && isAppLocale(requested) ? requested : defaultLocale;
  const messages = (await import(`../messages/${locale}.json`)).default;
  return {
    locale,
    messages,
    timeZone: 'Asia/Kolkata',
    onError(error) {
      // Missing keys are a release blocker (CI key-parity test); log loudly in development.
      if (process.env.NODE_ENV !== 'production') console.error(error.message);
    }
  };
});
