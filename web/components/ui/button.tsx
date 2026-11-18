import {cva, type VariantProps} from 'class-variance-authority';
import {Slot} from 'radix-ui';
import type {ComponentProps} from 'react';
import {cn} from '@/lib/utils';

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-sm font-semibold transition-[background-color,box-shadow,transform,color] duration-200 ease-out disabled:pointer-events-none disabled:opacity-50 active:translate-y-px [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-brand text-white shadow-glow-sm hover:bg-brand-hover hover:shadow-glow',
        gradient: 'bg-brand-gradient text-white shadow-glow-sm hover:shadow-glow hover:brightness-105',
        secondary: 'bg-surface text-ink border border-line-strong hover:border-brand hover:text-brand',
        ghost: 'text-ink hover:bg-pink-100 hover:text-brand',
        soft: 'bg-pink-100 text-brand hover:bg-pink-50',
        danger: 'bg-surface text-danger border border-danger/40 hover:bg-danger-50',
        dark: 'bg-white text-ink hover:bg-pink-50',
        link: 'text-brand underline-offset-4 hover:underline px-0 h-auto'
      },
      size: {
        sm: 'h-9 px-3 text-sm',
        md: 'h-11 px-5 text-[15px]',
        lg: 'h-13 px-7 text-base',
        icon: 'size-10'
      }
    },
    defaultVariants: {variant: 'primary', size: 'md'}
  }
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ComponentProps<'button'> & VariantProps<typeof buttonVariants> & {asChild?: boolean}) {
  const Comp = asChild ? Slot.Root : 'button';
  return <Comp className={cn(buttonVariants({variant, size}), className)} {...props} />;
}
