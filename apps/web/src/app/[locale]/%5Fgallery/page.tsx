'use client';

/**
 * The component workbench (F26).
 *
 * Every design rule in this product is enforced by reading — the accent means
 * AI and nothing else, a band never travels without its label, a card has a
 * shadow and a panel does not — and there was nowhere to see the components
 * side by side to check any of it. A reviewer had to find a screen that
 * happened to render the state they wanted, which for an error, a loading
 * shape or a full band ramp usually meant no screen at all.
 *
 * Deliberately not Storybook: a second toolchain with its own config, its own
 * server and its own way of mocking would need maintaining, and the fixtures
 * and the screenshot harness already exist. This is one route, rendered by the
 * app itself, with the app's own tokens and the app's own theme switch.
 *
 * Gated on fixture mode. It is a design surface, not a product screen, and it
 * has no business existing in a build a teacher can reach.
 */

import {
  AiBadge,
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  ConfidenceBar,
  Divider,
  EmptyState,
  ErrorState,
  Field,
  IconPrint,
  IconWarning,
  Input,
  KeyboardHint,
  LoadingState,
  MasteryBandTag,
  Panel,
  Pill,
  ProgressRing,
  Radio,
  SegmentedControl,
  Select,
  Skeleton,
  Slider,
  Spinner,
  Textarea,
  Toggle,
  type MasteryBand,
} from '@alppy/ui';
import { useTranslations } from 'next-intl';
import { notFound } from 'next/navigation';

import { isMockEnabled } from '@/lib/api/client';
import { useBandLabels } from '@/lib/bands';

const BANDS: MasteryBand[] = ['solid', 'ok', 'weak', 'fading', 'none'];

function Row({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-h3">{title}</h2>
      <div className="flex flex-wrap items-end gap-3">{children}</div>
    </section>
  );
}

export default function GalleryPage() {
  const bandLabels = useBandLabels();
  const tc = useTranslations('common');

  // `notFound()` rather than a redirect: outside fixture mode this route does
  // not exist, and saying so is the honest answer.
  if (!isMockEnabled()) notFound();

  return (
    <div className="mx-auto max-w-4xl" data-gallery>
      <h1 className="mb-2">Gallery</h1>
      <p className="mb-8 max-w-prose text-body-s text-ink-700">
        Every primitive in its states. Switch theme, contrast and calm from the settings
        screen — this page uses the same tokens as everything else, so what breaks here
        breaks everywhere.
      </p>

      <Row title="Button">
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button variant="primary" leadingIcon={<IconPrint />}>
          With icon
        </Button>
        <Button variant="primary" disabled>
          Disabled
        </Button>
        <Button variant="primary" loading busyLabel="Working…">
          Loading
        </Button>
      </Row>

      <Row title="Badge, Chip, Pill">
        <Badge>Default</Badge>
        <Badge variant="danger">Danger</Badge>
        <Badge variant="success">Success</Badge>
        <Badge variant="warn">Warn</Badge>
        <Chip>Chip</Chip>
        <Pill>Pill</Pill>
        {/* The one component allowed to wear the mandarin accent (DC-colour-06). */}
        <AiBadge label="IA" />
      </Row>

      <Row title="Mastery bands">
        {/* `label` is a required prop precisely so a caller cannot produce a
            bare coloured pill: colour is never the only channel (DC-colour-08). */}
        {BANDS.map((band) => (
          <MasteryBandTag key={band} band={band} label={bandLabels[band]} />
        ))}
      </Row>

      <Row title="Mastery bands with coverage">
        {BANDS.slice(0, 3).map((band) => (
          <MasteryBandTag
            key={band}
            band={band}
            label={bandLabels[band]}
            caption="2 sur 3"
          />
        ))}
      </Row>

      <Row title="Confidence">
        <ConfidenceBar value={0.97} label="97 %" />
        <ConfidenceBar value={0.41} label="41 %" />
        <ProgressRing value={0.62} centre="62 %" label="Progress" size={56} />
        <Spinner size={28} />
      </Row>

      <Row title="Form controls">
        <Field label="Input">
          <Input defaultValue="Fractions" />
        </Field>
        <Field label="Invalid" error="Ce code n'est pas valide.">
          <Input defaultValue="11ABC" invalid />
        </Field>
        <Field label="Select">
          <Select defaultValue="a">
            <option value="a">Option A</option>
            <option value="b">Option B</option>
          </Select>
        </Field>
        <Field label="Textarea">
          <Textarea defaultValue="Explique ta démarche." rows={2} />
        </Field>
      </Row>

      <Row title="Toggles">
        <Checkbox label="Checkbox" defaultChecked />
        <Radio name="gallery-radio" value="one" label="Radio" defaultChecked />
        <Toggle label="Toggle" checked onCheckedChange={() => {}} />
        <SegmentedControl
          value="one"
          label="Segmented"
          onValueChange={() => {}}
          options={[
            { value: 'one', label: 'One' },
            { value: 'two', label: 'Two' },
          ]}
        />
        <KeyboardHint keys={['N']} />
      </Row>

      <Row title="Slider">
        <div className="w-64">
          <Slider min={1} max={8} value={4} onValueChange={() => {}} aria-label="Séries" />
        </div>
      </Row>

      {/* A card is a separate object; a panel is a subdivision of the one you
          are already in (DC-shape-01). Side by side is the only way to see it. */}
      <section className="mb-8">
        <h2 className="mb-3 text-h3">Card vs Panel</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <p className="text-body-s">Card — radius lg, solid edge, shadow.</p>
            <Panel className="mt-3">
              <p className="text-body-s">Panel inside it — radius md, border, no shadow.</p>
            </Panel>
          </Card>
          <Card tint="warm">
            <p className="text-body-s">Card, warm tint.</p>
          </Card>
        </div>
      </section>

      <Divider />

      <section className="mb-8">
        <h2 className="mb-3 text-h3">Screen states</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Card flush>
            <LoadingState shape="list" label={tc('loading')} rows={3} />
          </Card>
          <Card flush>
            <LoadingState shape="sheet" label={tc('loading')} />
          </Card>
          <Card flush>
            <EmptyState
              size="sm"
              title="Rien ici"
              description="Une phrase qui dit quoi faire ensuite."
              action={<Button variant="primary">Commencer</Button>}
            />
          </Card>
          <Card flush>
            <ErrorState
              announce={false}
              title="Quelque chose n'a pas fonctionné"
              description="Réessayez dans un instant."
              action={<Button>{tc('retry')}</Button>}
            />
          </Card>
        </div>
      </section>

      <Row title="Skeleton">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-24" />
        <IconWarning />
      </Row>
    </div>
  );
}
