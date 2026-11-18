import {createNavigation} from 'next-intl/navigation';
import {routing} from './routing';

/** Locale-aware Link/redirect/router: never hard-code `/en` in links. */
export const {Link, redirect, usePathname, useRouter, getPathname} = createNavigation(routing);
