-- Esquema de la base de datos (PostgreSQL / Supabase).
-- OPCIONAL: la aplicación crea estas tablas automáticamente la primera vez que se conecta.
-- Úsalo si prefieres crearlas a mano desde Supabase → SQL Editor.

create table if not exists volunteers (
    id          serial primary key,
    name        varchar(120) not null,
    name_key    varchar(120) not null unique,      -- nombre normalizado (evita duplicados)
    created_at  timestamp not null,
    updated_at  timestamp not null
);

create table if not exists activities (
    id             serial primary key,
    name           varchar(150) not null,
    name_key       varchar(150) not null,
    activity_date  date not null,                  -- fecha de la actividad
    start_time     time not null,
    created_at     timestamp not null,
    constraint uq_activity_name_date unique (name_key, activity_date)
);

create table if not exists tardies (
    id             serial primary key,
    activity_id    integer not null references activities(id),
    volunteer_id   integer not null references volunteers(id),
    start_time     time not null,                  -- copia de la hora de inicio al registrar
    arrival_time   time not null,
    delay_minutes  integer not null,
    penalty        numeric(10, 2) not null,
    rules_snapshot text not null,                  -- reglas vigentes al registrar (JSON)
    status         varchar(20) not null,           -- Pendiente | Pagado | Anulado
    notes          text,
    registered_at  timestamp not null,             -- fecha de registro (hora de Lima)
    updated_at     timestamp not null,
    void_reason    text,
    client_token   varchar(64) unique              -- evita duplicados por doble envío
);

-- Un voluntario solo puede tener una tardanza vigente por actividad.
create unique index if not exists uq_tardy_activity_volunteer_active
    on tardies (activity_id, volunteer_id) where status <> 'Anulado';

create table if not exists payments (
    id            serial primary key,
    tardy_id      integer not null references tardies(id),
    payment_date  date not null,
    amount        numeric(10, 2) not null,
    method        varchar(30) not null,            -- Yape | Plin | Transferencia | Efectivo
    notes         text,
    created_at    timestamp not null,
    voided        boolean not null default false,
    void_reason   text,
    voided_at     timestamp
);
create index if not exists ix_payments_tardy_id on payments (tardy_id);

create table if not exists settings (
    key         varchar(60) primary key,
    value       text not null,                     -- JSON
    updated_at  timestamp not null
);

create table if not exists audit_log (
    id          serial primary key,
    created_at  timestamp not null,
    entity      varchar(30) not null,
    entity_id   integer,
    action      varchar(30) not null,
    details     text                               -- JSON
);

-- Seguridad: bloquea el acceso por la API pública de Supabase (clave anon).
-- La aplicación se conecta como dueña de las tablas y no se ve afectada.
alter table volunteers enable row level security;
alter table activities enable row level security;
alter table tardies    enable row level security;
alter table payments   enable row level security;
alter table settings   enable row level security;
alter table audit_log  enable row level security;
