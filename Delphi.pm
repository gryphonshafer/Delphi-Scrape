package Delphi;
use exact;

use Carp 'croak';
use Date::Parse 'str2time';
use IO::Socket::SSL;
use Mojo::DOM;
use Mojo::JSON 'decode_json';
use Mojo::URL;
use Mojo::UserAgent;
use Readonly::Tiny 'Readonly';
use Time::HiRes 'sleep';
use WWW::Mechanize::PhantomJS;

Readonly my $forums_url   => 'https://forums.delphiforums.com';
Readonly my $profiles_url => 'https://profiles.delphiforums.com';

my %archive_cache;

sub new ( $package, $self ) {
    for ( qw( forum username password ) ) {
        croak(qq{"$_" not defined properly}) unless ( defined $self->{$_} and length $self->{$_} );
    }

    # setup phantom mech and phantom driver
    $self->{mech}   = WWW::Mechanize::PhantomJS->new;
    $self->{driver} = $self->{mech}->driver;

    $self->{mech}->viewport_size({ width => 1100, height => 990 });
    $self->{mech}->eval_in_phantomjs(
        'this.settings.userAgent = arguments[0]',
        'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0',
    );

    # setup useragent
    $self->{ua} = Mojo::UserAgent->new;
    $self->{ua}->transactor->name('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:48.0) Gecko/20100101 Firefox/48.0');
    $self->{ua}->max_redirects(5);

    return bless( $self, __PACKAGE__ );
}

sub login ($self) {
    unless ( $self->{logged_in} ) {
        # visit initial page
        $self->{mech}->get("$forums_url/$self->{forum}");

        $self->{driver}->switch_to_frame('BrandFrame');
        $self->{mech}->follow_link( text_contains => '(login)' );

        # fill out and submit login form
        $self->{mech}->by_id( 'lgnForm_username', single => 1 )->clear;
        $self->{mech}->by_id( 'lgnForm_password', single => 1 )->clear;
        $self->{mech}->by_id( 'lgnForm_username', single => 1 )->send_keys( $self->{username} );
        $self->{mech}->by_id( 'lgnForm_password', single => 1 )->send_keys( $self->{password} );
        $self->{mech}->by_id( 'df_lgnbtn', single => 1 )->click;

        # wait for login to complete
        my $waits;
        while ( $self->{mech}->title =~ /log\s*in/i ) {
            die "Login failed after 10 seconds\n" if ( $waits++ > 10 );
            sleep 1;
        }

        $self->{logged_in} = 1;
    }

    # copy cookies from phantom driver into useragent's cookie jar in a very
    # careful (and stupid) way to "hack" the domain so all cookies will all
    # show up for the forums URL
    $self->{ua}->cookie_jar->add(
        map {
            Mojo::Cookie::Response->new(
                name   => $_->{name},
                value  => $_->{value},
                domain => 'forums.delphiforums.com',
                path   => '/',
            )
        } @{ $self->{driver}->get_all_cookies }
    );

    return $self;
}

sub most_recent_thread ($self) {
    $self->login;

    my ( $most_recent_thread, $tries );
    while ( ++$tries < 3 ) {
        # visit messages page
        $self->{mech}->get("$forums_url/$self->{forum}/messages");

        # select the nav/list frame
        $self->{driver}->switch_to_frame('LowerFrame');
        $self->{driver}->switch_to_frame('ListWin');

        # find the most recent message thread ID from links
        $most_recent_thread = Mojo::DOM->new( $self->{driver}->get_page_source )
            ->find('a')->map( attr => 'href' )
            ->grep( sub { $_ and m|/$self->{forum}/messages/| } )
            ->map( sub { m|(\d+)/\d+|; $1 } )
            ->sort( sub { $b <=> $a } )->first;

        last if ($most_recent_thread);
        sleep 1;
    }

    die "Failed to find most recent thread ID after 3 attempts\n" unless ($most_recent_thread);
    return $most_recent_thread;
}

sub msgs_dom ( $self, $current_thread = $self->most_recent_thread, $message_number = 1 ) {
    $self->login;

    sleep $self->{lag};

    my $msg = ( $current_thread =~ /\./ ) ? $current_thread : "$current_thread.$message_number";

    # visit page of first message in thread
    my $err;
    try {
        $self->{mech}->get("$forums_url/$self->{forum}/messages?msg=$msg");
    }
    catch ($e) {
        return;
    }

    # select the messages frame
    $self->{driver}->switch_to_frame('LowerFrame');
    $self->{driver}->switch_to_frame('MsgWin');

    # build a DOM object of the messages HTML
    return Mojo::DOM->new( $self->{driver}->get_page_source );
}

sub thread_data ( $self, $current_thread = $self->most_recent_thread ) {
    my ( $msgs, $msg_unsubj, $tries );

    while ( ++$tries < 3 ) {
        $msgs = $self->msgs_dom($current_thread);
        return unless ($msgs);

        my $msghead = $msgs->at('table#msgUN tr.msgCdwd td.msghead');
        return if ( $msghead and $msghead->all_text =~ /No discussions/ );

        $msg_unsubj = $msgs->at('td#msgUNsubj');

        last if ($msg_unsubj);
        sleep 1;
    }
    die "Failed to find topic summary in page after 3 attempts\n" unless ($msg_unsubj);
    my $summary_text = $msg_unsubj->all_text // q{};
    $summary_text =~ s/\s+/ /g;
    $summary_text =~ s/(^\s+|\s+$)//g;

    my %metadata;
    if (
        $summary_text =~ /
            (?<folder>.+?)
            (?:\s+-\s+(?<topic>.*?\S))?
            \s*\(
            (?<views>\d+)
        /x
    ) {
        %metadata = %+;
        $metadata{folder} =~ s/(^\s+|\s+$)//g if ( defined $metadata{folder} );
        $metadata{topic}  =~ s/(^\s+|\s+$)//g if ( defined $metadata{topic} );
    }
    else {
        %metadata = ();
    }
    my $total_msg = 0;
    my @messages;

    while (1) {
        push( @messages, grep { defined } map {
            my $msg = $_;
            $total_msg = $1 if ( not $total_msg and $msg->at('td.msgNum')->all_text =~ /\(\d+ of (\d+)\)/ );

            ( my $date = $msg->at('td.msgDate')->all_text ) =~ s/\s+$//;
            $date =~ s/-/ /g;
            $date = str2time($date);

            unless ($date) {
                undef;
            }
            else {
                $date = localtime($date);

                $msg->at('table.df-msginner td.wintiny')->all_text =~ m|
                    (?<id>\d+\.\d+)\s*
                    in\s*reply\s*to\s*
                    (?<in_reply_to>\d+\.\d+)
                |x;
                my %ids = %+;
                $ids{id} //= ( $current_thread =~ /\./ ) ? $current_thread : "$current_thread.1";

                my $body_container = $msg->at('td.msgtxt');
                return unless ($body_container);

                my $body       = $body_container->at('div.os-msgbody');
                my $poll_table = $body_container->at('table.polltable');
                my $poll_html  = $poll_table ? $poll_table->to_string : undef;

                my $content_html = q{};
                $content_html .= $body->content if ($body);
                $content_html .= $poll_html     if ( defined $poll_html and ( not $body or index( $content_html, $poll_html ) == -1 ) );
                $content_html  = $body_container->content if ( $content_html eq q{} );

                my $scope_for_images = $body // $poll_table // $body_container;
                my $images = $scope_for_images->find('img')->grep( sub { $_->attr('src') } )->map( sub {
                    my $src = $_->attr('src');
                    unless ( $src =~ m|^\w+://| ) {
                        $src = $forums_url . $_->attr('src');
                        $_->attr( 'src' => $src );
                    }
                    $src;
                } )->to_array;

                my $poll;
                if ($poll_table) {
                    my $question = $poll_table->at('span.winbig');
                    my $options_table = $poll_table->find('table')->first;
                    my @options;

                    if ($options_table) {
                        my @rows = $options_table->find('tr')->each;
                        for ( my $i = 0; $i < @rows; $i++ ) {
                            my $row = $rows[$i];
                            next unless ( $row and ref $row and $row->can('at') );
                            my $label_cell = $row->at('td');
                            next unless ($label_cell);

                            my $label = $label_cell->all_text;
                            $label =~ s/\s+/ /g;
                            $label =~ s/(^\s+|\s+$)//g;
                            next unless length $label;

                            my $bar_class;
                            if ( my $bar_cell = $row->find('td')->grep( sub {
                                my $class = $_->attr('class') // q{};
                                $class =~ /\bpollbar\d+\b/;
                            } )->first ) {
                                my $class_attr = $bar_cell->attr('class') // q{};
                                ($bar_class) = $class_attr =~ /(pollbar\d+)/;
                                $bar_class //= $class_attr;
                            }

                            my $stats_row = ( $i + 1 < @rows ) ? $rows[ $i + 1 ] : undef;
                            my ( $votes, $percent );
                            if ($stats_row) {
                                my $stats_text = ( $stats_row->can('all_text') ) ? $stats_row->all_text : q{};
                                $stats_text =~ s/\s+/ /g;
                                if ( $stats_text =~ /([\d,]+)\s*votes/i ) {
                                    ( $votes = $1 ) =~ s/,//g;
                                }
                                if ( $stats_text =~ /\(([\d.]+)%\)/ ) {
                                    $percent = $1 + 0;
                                }
                                $i++;
                            }

                            push(
                                @options,
                                +{
                                    ( length $label ? ( label => $label ) : () ),
                                    ( defined $votes ? ( votes => +$votes ) : () ),
                                    ( defined $percent ? ( percent => $percent ) : () ),
                                    ( $bar_class ? ( bar_class => $bar_class ) : () ),
                                }
                            );
                        }
                    }

                    my $details_cell = $poll_table->find('td.msgtxt')->last;
                    my ( $total_votes, $status_text, $details_html );
                    if ($details_cell) {
                        my $details_text = $details_cell->all_text // q{};
                        $details_text =~ s/\s+/ /g;
                        $details_text =~ s/(^\s+|\s+$)//g;
                        if ( $details_text =~ /([\d,]+)\s+people\s+voted/i ) {
                            ( $total_votes = $1 ) =~ s/,//g;
                            $total_votes += 0;
                        }
                        $status_text = $details_text if ($details_text);
                        $details_html = $details_cell->content;
                    }

                    $poll = +{
                        ( $question    ? ( question    => $question->all_text =~ s/(^\s+|\s+$)//gr ) : () ),
                        ( @options     ? ( options     => \@options ) : () ),
                        ( defined $total_votes ? ( total_votes => $total_votes ) : () ),
                        ( $details_html ? ( details_html => $details_html ) : () ),
                        ( $status_text  ? ( details_text => $status_text )  : () ),
                    };
                    $poll = undef unless ( $poll and keys %$poll );
                }

                my $from = $msg->at('td.msgFname')->all_text // q{};
                $from =~ s/\s+/ /g;
                $from =~ s/(^\s+|\s+$)//g;
                my $from_unread = $from =~ s/\s+unread$//i ? 1 : 0;

                my $to = $msg->at('td.msgTname')->all_text // q{};
                $to =~ s/\s+/ /g;
                $to =~ s/(^\s+|\s+$)//g;
                my $to_unread = $to =~ s/\s+unread$//i ? 1 : 0;

                +{
                    %ids,
                    date        => $date,
                    from        => $from,
                    to          => $to,
                    content     => $content_html,
                    images      => $images,
                    attachments => [
                        map {
                            ( my $size = $_->text ) =~ s/(^\s+|\s+$)//g;
                            my $link = $_->at('a');

                            +{
                                name => $link->at('span.text')->text,
                                href => $forums_url . $link->attr('href'),
                                size => $size,
                            };
                        } $msg->find('li.os-attachment')->each
                    ],
                    ( $from_unread ? ( from_status => 'unread' ) : () ),
                    ( $to_unread   ? ( to_status   => 'unread' ) : () ),
                    ( $poll ? ( poll => $poll ) : () ),
                };
            }
        } $msgs->find('table')->grep( sub { $_->attr('id') and $_->attr('id') =~ /^df_msg_\d+/ } )->each );

        # decide to loop if there's a "Keep Reading" button with a message ID
        my $keep_reading = $msgs->find('button.os-btn')->grep( sub {
            my $span = $_->at('span');
            $span and $span->text and $span->text =~ /Keep Reading/;
        } );
        if ( $keep_reading and $keep_reading->size ) {
            my ($next_msg_id) = $keep_reading->first->attr('onclick') =~ /\bmsg\s*=\s*\d+\.(\d+)/;
            if ($next_msg_id) {
                $msgs = $self->msgs_dom( $current_thread, $next_msg_id );
                last unless ($msgs);
                next;
            }
        }

        last;
    };

    return {
        thead_id => $current_thread,
        metadata => \%metadata,
        messages => \@messages,
    };
}

sub profile_data ( $self, $profile ) {
    $self->login;

    sleep $self->{lag};

    $self->{mech}->get("$profiles_url/$profile");

    my $dom = Mojo::DOM->new( $self->{mech}->content );

    return {
        map {
            my $text = $_;
            $text =~ s/(^\s+|\s+$)//g;
            $text =~ s/\s+/ /g;
            $text;
        } (
            (
                map { split( /:/, $_, 2 ) }
                @{ $dom->find('div.os-usermenu > ul > li')->map('text')->to_array }
            ),
            (
                map { map { $_->text } @$_ }
                grep { $_->[0] and $_->[1] }
                map { [ $_->at('label'), $_->at('span') ] }
                $dom->find('div.os-jabberform div.os-field')->each
            ),
        ),
        profile_id => $profile,
    };
}

sub save_page_as_png ( $self, $png_filename = 'page.png' ) {
    open( my $png, '>', $png_filename );
    binmode( $png, ':raw' );
    print $png $self->{mech}->content_as_png;
    close $png;

    return $self;
}

sub pull_binary ( $self, $url, $filename ) {
    $self->login;

    my $result;
    my $used_archive;
    try {
        $result = $self->{ua}->get($url)->result;
    }
    catch ($e) {}

    if ( not ( $result and $result->code == 200 ) ) {
        if ( not $result or $result->code =~ /^40[34]$/ ) {
            if ( my $archive_url = $self->_archive_snapshot($url) ) {
                try {
                    my $archive_result = $self->{ua}->get($archive_url)->result;
                    if ( $archive_result and $archive_result->code == 200 ) {
                        $result       = $archive_result;
                        $used_archive = 1;
                    }
                    elsif ($archive_result) {
                        $result = $archive_result;
                    }
                }
                catch ($e) {}
            }
        }
    }

    if ( $result and $result->code == 200 ) {
        open( my $output, '>', $filename ) or die "$!: $filename\n";
        binmode( $output, ':raw' );
        print $output $result->body;
        close $output;
        print "      Recovered via Internet Archive\n" if ($used_archive);
    }

    return ($result) ? $result->code : 0;
}

sub _archive_snapshot ( $self, $url ) {
    return $archive_cache{$url} if ( exists $archive_cache{$url} );

    my $api_url = Mojo::URL->new('https://web.archive.org/cdx/search/cdx')->query(
        {
            url    => $url,
            output => 'json',
            filter => 'statuscode:200',
            limit  => 1,
        }
    );

    my $response;
    try {
        $response = $self->{ua}->get($api_url)->result;
    }
    catch ($e) {
        return ( $archive_cache{$url} = undef );
    }

    return ( $archive_cache{$url} = undef ) unless ( $response and $response->code == 200 );

    my $data = eval { decode_json( $response->body ) };
    return ( $archive_cache{$url} = undef ) unless ( ref($data) eq 'ARRAY' and @$data > 1 );

    my $row = $data->[1];
    return ( $archive_cache{$url} = undef ) unless ( ref($row) eq 'ARRAY' and @$row >= 3 );

    my $timestamp = $row->[1];
    my $original  = $row->[2] || $url;
    return ( $archive_cache{$url} = undef ) unless ($timestamp);

    my $archive_url = Mojo::URL->new("https://web.archive.org/web/$timestamp/$original")->to_string;
    return ( $archive_cache{$url} = $archive_url );
}

sub get_updated_list ( $self, $days = 7 ) {
    $self->login;

    my $this_url = $forums_url . '/n/find/results.asp?webtag=' . $self->{forum} . '&o=newest&af=' . $days;
    my %ids;

    while ($this_url) {
        my $links = $self->{ua}->get($this_url)->result->dom->find('a');

        my $next = $links->grep( sub {
            my $span = $_->at('span');
            $span and $span->text eq 'Next 50';
        } )->first;

        $this_url = ($next)
            ? Mojo::URL->new( $next->attr('href') )->to_abs( Mojo::URL->new($this_url) )
            : undef;

        %ids = ( %ids, map { @$_ } @{
            $links->map( attr => 'href' )->grep( sub { $_ and /\bmsg=/ } )
                ->map( sub { /\bmsg=(\d+)\.(\d+)/; [ $1, $2 ] } )
                ->sort( sub { $b->[0] <=> $a->[0] or $b->[1] <=> $a->[1] } )
                ->map( sub { [ $_->[0], $_->[0] . '.' . $_->[1] ] } )
                ->to_array
        } );
    }

    return [ map { $ids{$_} } sort { $b <=> $a } keys %ids ];
}

1;
